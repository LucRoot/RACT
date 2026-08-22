"""Cross-function grouping rules for the retrieve primitive.

Master spec ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Chunk
Discipline / §Cross-Function Grouping names four rules under which
some symbols are meaningless in isolation and MUST be retrieved
together with their companions:

1. A Python dataclass retrieves with every method defined in its
   body.
2. A Rust trait retrieves with every ``impl <Trait> for <Type>``
   block, *when the query is about the trait* (i.e., the trait's
   name appears in :attr:`RetrievalQuery.symbol_names`; a query
   focused on the concrete impl type does NOT drag the trait's
   siblings back into the bundle).
3. A test function retrieves with its subject function
   (``test_foo`` companions ``foo``; ``class TestFoo`` companions
   ``class Foo``). Directionality: test → subject only. The
   converse (a subject-focused query pulling in every test) would
   explode the bundle for common infrastructure symbols.
4. A Python function or method retrieves with every module-scope
   type alias its signature references.

Ships:

- :class:`GroupingRules` — frozen dataclass whose fields
  independently toggle each of the four rules, plus a
  ``languages`` filter that lets a config opt out of a language
  entirely.
- :class:`SymbolGroup` — frozen dataclass returned by
  :func:`group_symbols`; carries the primary
  :class:`~ract.memory.symbol_index.SymbolRow` plus its
  companion rows and a ``rule`` string naming which rule fired.
- :func:`group_symbols` — the pure grouping function. Takes a
  list of symbols and returns one group per input (empty
  companions when no rule fires).
- :func:`load_grouping_rules` — YAML loader for
  ``.ract/grouping_rules.yaml`` (optional; defaults ship).

The grouping function is pure — it consults the shipped
:class:`~ract.memory.symbol_index.SymbolIndex` to find companion
rows via ``find_in_file`` / ``find_by_name`` / ``find_by_pattern``
but does NOT read source files, mutate the index, emit events, or
seat chunks. Bundle-assembly wiring (chunk rendering + budget
cascade) lives at the retrieve primitive's call site
(:mod:`ract.memory.retrieve`).

Backward compatibility. This module is purely additive. Callers
who never construct a :class:`GroupingRules` and never toggle
:attr:`RetrievalQuery.grouping_enabled` retain today's behavior
(default is on, but rules only fire when the primary symbol
matches; a symbol matching no rule contributes an empty group and
no companions).

Reference: audit ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
finding C-1 (HIGH) — cross-function grouping absent; grep of
``src/ract/memory/`` returned no owner. This module ships the owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.symbol_index import SymbolIndex, SymbolRow


# ---------------------------------------------------------------------------
# Rule names (closed vocabulary)
# ---------------------------------------------------------------------------

RULE_DATACLASS_METHODS: str = "dataclass_methods"
"""Rule name for Python dataclass + methods grouping."""

RULE_TRAIT_IMPLS: str = "trait_impls"
"""Rule name for Rust trait + impl blocks grouping."""

RULE_TEST_SUBJECT: str = "test_subject"
"""Rule name for test function + subject function grouping."""

RULE_FUNCTION_TYPE_ALIASES: str = "function_type_aliases"
"""Rule name for Python function + module-scope type aliases grouping."""

RULE_NONE: str = ""
"""Placeholder rule name for a primary symbol that matched no rule."""


LEGAL_RULES: frozenset[str] = frozenset(
    {
        RULE_DATACLASS_METHODS,
        RULE_TRAIT_IMPLS,
        RULE_TEST_SUBJECT,
        RULE_FUNCTION_TYPE_ALIASES,
    }
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupingRules:
    """Per-project toggles for cross-function grouping rules.

    Every rule defaults on (matches the shipped default the master
    spec assumes). A rule set to ``False`` becomes a no-op — the
    corresponding :func:`group_symbols` branch returns an empty
    companion tuple for that primary. The ``languages`` filter is a
    frozen set of language labels (``python`` / ``typescript`` /
    ``rust`` / ``go``) — a primary whose ``language`` is outside
    the set produces an empty group regardless of the per-rule
    toggles.
    """

    dataclass_methods: bool = True
    trait_impls: bool = True
    test_subject: bool = True
    function_type_aliases: bool = True
    languages: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"python", "typescript", "rust", "go"}
        )
    )


@dataclass(frozen=True)
class SymbolGroup:
    """A cohesive set of symbols retrieved together.

    ``primary`` is the symbol that surfaced from the query.
    ``companions`` is the tuple of :class:`SymbolRow` values pulled
    in by whichever rule fired; empty when no rule matched (the
    "primary-only" group). ``rule`` names the rule fired — one of
    :data:`LEGAL_RULES` or :data:`RULE_NONE` for the empty case.

    Deterministic ordering: :func:`group_symbols` returns companions
    sorted by ``(file_path, start_line, name)`` so two invocations
    on the same input produce byte-identical groups.
    """

    primary: SymbolRow
    companions: tuple[SymbolRow, ...] = ()
    rule: str = RULE_NONE


# ---------------------------------------------------------------------------
# Rule detectors
# ---------------------------------------------------------------------------


def _looks_like_dataclass(symbol: SymbolRow) -> bool:
    """Return True when ``symbol`` is a Python ``@dataclass`` class.

    Detection: symbol.kind == "class", language == "python", AND
    ``@dataclass`` appears in the signature (which for a decorated
    class chunker holds the whole decorated_definition first line,
    per :func:`ract.memory.languages.python._signature`).

    Also matches ``@dataclass(frozen=True)`` and
    ``@dataclasses.dataclass`` variants via substring check on
    ``@dataclass``. The check is intentionally lax — a decorator
    whose runtime type happens to be ``dataclass`` under a different
    import name (a project-local alias) will NOT match, and the
    grouping simply does not fire for that class. Non-firing is the
    safe default: the primary still surfaces from the query, and the
    caller can request the methods explicitly.
    """
    if symbol.kind != "class":
        return False
    if (symbol.language or "").lower() != "python":
        return False
    sig = symbol.signature or ""
    if "@dataclass" not in sig:
        return False
    return True


def _looks_like_trait(symbol: SymbolRow) -> bool:
    """Return True when ``symbol`` is a Rust ``trait`` declaration."""
    if symbol.kind != "trait":
        return False
    if (symbol.language or "").lower() != "rust":
        return False
    return True


_PYTHON_TEST_PREFIX = "test_"
_PYTHON_TEST_CLASS_PREFIX = "Test"


def _looks_like_test(symbol: SymbolRow) -> tuple[bool, str, str]:
    """Return ``(matches, subject_name, subject_kind)``.

    Test detection is language-agnostic on the naming convention
    (Python + Rust + Go all use ``test_`` / ``Test`` prefixes for
    the pytest / go test / cargo test conventions). ``subject_kind``
    is the expected kind of the subject symbol; the caller uses it
    to filter the ``find_by_name`` result set.
    """
    name = symbol.name or ""
    kind = symbol.kind or ""
    if kind in {"function", "method"} and name.startswith(_PYTHON_TEST_PREFIX):
        subject = name[len(_PYTHON_TEST_PREFIX) :]
        if subject:
            return True, subject, kind
    if kind == "class" and name.startswith(_PYTHON_TEST_CLASS_PREFIX):
        subject = name[len(_PYTHON_TEST_CLASS_PREFIX) :]
        if subject:
            return True, subject, "class"
    return False, "", ""


# Identifiers a Python signature may contain that we conservatively
# skip when scanning for type-alias references. Keeps the scan cheap
# and avoids false positives on parameter names / builtins.
_PY_SIG_STOPWORDS: frozenset[str] = frozenset(
    {
        "def", "async", "self", "cls", "None", "True", "False",
        "return", "if", "else", "elif", "for", "while", "in",
        "not", "and", "or", "int", "str", "bool", "float", "bytes",
        "list", "dict", "set", "tuple", "frozenset", "Any", "Union",
        "Optional", "Callable", "Sequence", "Iterable", "Iterator",
        "Mapping", "MutableMapping", "MutableSequence", "type",
    }
)


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _extract_identifiers(signature: str) -> list[str]:
    """Return every identifier-shaped token in ``signature``.

    Deterministic left-to-right scan; duplicates preserved for
    downstream de-dup at the seat step. Skips :data:`_PY_SIG_STOPWORDS`.
    """
    if not signature:
        return []
    out: list[str] = []
    for match in _IDENTIFIER_RE.finditer(signature):
        token = match.group(0)
        if token in _PY_SIG_STOPWORDS:
            continue
        out.append(token)
    return out


def _looks_like_function_for_type_aliases(symbol: SymbolRow) -> bool:
    """Return True when ``symbol`` is a Python function or method."""
    if symbol.kind not in {"function", "method"}:
        return False
    if (symbol.language or "").lower() != "python":
        return False
    return True


# ---------------------------------------------------------------------------
# Companion lookup helpers
# ---------------------------------------------------------------------------


def _sorted_rows(rows: list[SymbolRow]) -> list[SymbolRow]:
    """Return ``rows`` sorted deterministically for reproducible groups."""
    return sorted(
        rows,
        key=lambda r: (
            r.file_path or "",
            r.start_line if r.start_line is not None else 0,
            r.name or "",
            r.kind or "",
        ),
    )


def _find_dataclass_methods(
    primary: SymbolRow, index: SymbolIndex
) -> list[SymbolRow]:
    """Return every method whose source range lies inside ``primary``'s
    class body.

    Uses :meth:`SymbolIndex.find_in_file` and filters on
    ``kind == "method"`` plus ``primary.start_line <= method.start_line
    <= primary.end_line``. The chunker today emits
    ``parent_symbol_id = None`` at parse time (spec calls that a
    Flagged gap for module_02); the line-range fallback is the
    correct-by-construction alternative until the parent linkage
    lands.
    """
    if primary.start_line is None or primary.end_line is None:
        return []
    if not primary.file_path:
        return []
    all_in_file = index.find_in_file(primary.file_path)
    companions: list[SymbolRow] = []
    for row in all_in_file:
        if row.kind != "method":
            continue
        if row.start_line is None:
            continue
        if row.start_line < primary.start_line:
            continue
        if row.start_line > primary.end_line:
            continue
        # Deduplicate against the primary itself (defensive; a class
        # is not a method but a stray equality would harm nothing).
        if row.id is not None and row.id == primary.id:
            continue
        companions.append(row)
    return _sorted_rows(companions)


_IMPL_HEAD_RE = re.compile(r"^impl(?:\s*<[^>]*>)?\s+([A-Za-z_][A-Za-z0-9_:]*)")


def _find_trait_impls(
    primary: SymbolRow, index: SymbolIndex
) -> list[SymbolRow]:
    """Return every ``impl <Trait> for <Type>`` row where ``<Trait>``
    is ``primary.name``.

    Rust impl rows are emitted with ``kind == "impl"`` and
    ``name == "impl <Trait> for <Type>"`` (see
    :func:`ract.memory.languages.rust._impl_name`). The lookup uses
    :meth:`SymbolIndex.find_by_pattern` with a regex anchored on
    ``impl <Trait> for`` so a lone-type impl (``impl Foo``, no
    trait) does not spuriously match. Namespaced traits
    (``crate::mod::Trait``) match the trailing name segment.
    """
    trait_name = primary.name or ""
    if not trait_name:
        return []
    # Regex escapes any character that could be a metacharacter (rare
    # in Rust identifiers, but a leading ``r#`` raw-identifier would
    # trip an unescaped scan).
    escaped = re.escape(trait_name)
    # SQLite's REGEXP hook runs the pattern via ``re.search`` under
    # the module's :func:`ract.memory.symbol_index.SymbolIndex` shim.
    # We anchor on the ``impl`` keyword to skip stray matches inside
    # a doc string. Namespaced traits: ``impl foo::Bar for X`` still
    # matches ``Bar`` because the ``impl`` keyword walker below
    # accepts a ``[A-Za-z_:]`` head that can carry ``::``.
    pattern = rf"^impl\b.*\b{escaped}\b\s+for\b"
    try:
        rows = index.find_by_pattern(pattern, kind_filter="impl")
    except Exception:
        rows = []
    # Confirm each hit via the parser rendered ``impl X for Y`` head
    # to defend against a false positive when the trait name appears
    # in the ``for <Type>`` position of a different impl.
    confirmed: list[SymbolRow] = []
    for row in rows:
        head = (row.name or "").split(" for ", 1)[0]
        match = _IMPL_HEAD_RE.match(head)
        if match is None:
            continue
        head_trait = match.group(1).split("::")[-1]
        if head_trait == trait_name:
            confirmed.append(row)
    return _sorted_rows(confirmed)


def _find_test_subject(
    primary: SymbolRow, index: SymbolIndex
) -> list[SymbolRow]:
    """Return the subject symbol(s) for a test symbol.

    ``test_foo`` → symbols named ``foo`` (kind ``function`` or
    ``method``); ``class TestFoo`` → symbols named ``Foo``
    (kind ``class``). Excludes the primary itself. Multiple hits
    are all included (an ambiguous test name maps to every possible
    subject — the retrieve caller can pare down via file_scope).
    """
    matches, subject_name, subject_kind = _looks_like_test(primary)
    if not matches:
        return []
    # We deliberately do NOT constrain by file_path — a test in
    # ``tests/`` should pull the subject from ``src/``.
    rows = index.find_by_name(subject_name)
    companions: list[SymbolRow] = []
    for row in rows:
        if row.id is not None and primary.id is not None and row.id == primary.id:
            continue
        if subject_kind == "class":
            if row.kind != "class":
                continue
        else:
            if row.kind not in {"function", "method"}:
                continue
        companions.append(row)
    return _sorted_rows(companions)


def _find_function_type_aliases(
    primary: SymbolRow, index: SymbolIndex
) -> list[SymbolRow]:
    """Return every module-scope ``type`` symbol referenced in
    ``primary``'s signature.

    Two-step scan:

    1. Extract identifier-shaped tokens from
       :attr:`SymbolRow.signature` (skipping
       :data:`_PY_SIG_STOPWORDS`).
    2. For each unique token, :meth:`SymbolIndex.find_by_name` with
       ``kind_filter="type"`` and keep every hit.

    De-duplication runs on (id, name); a name that resolves to two
    different type rows (a rare aliasing across files) contributes
    both.
    """
    signature = primary.signature or ""
    if not signature:
        return []
    tokens = _extract_identifiers(signature)
    seen: set[str] = set()
    companions: list[SymbolRow] = []
    seen_ids: set[int] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        try:
            rows = index.find_by_name(token, kind_filter="type")
        except Exception:
            rows = []
        for row in rows:
            if row.id is not None and row.id == primary.id:
                continue
            if row.id is not None and row.id in seen_ids:
                continue
            if row.id is not None:
                seen_ids.add(row.id)
            companions.append(row)
    return _sorted_rows(companions)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def group_symbols(
    symbols: list[SymbolRow],
    rules: GroupingRules,
    *,
    index: SymbolIndex,
    query: Any | None = None,
) -> list[SymbolGroup]:
    """Group each symbol in ``symbols`` with its cohesive companions.

    Returns one :class:`SymbolGroup` per input symbol, in input
    order. A symbol with no matching rule contributes a group with
    empty ``companions`` and ``rule=RULE_NONE``.

    Rule precedence (first match wins per symbol):

    1. :attr:`GroupingRules.trait_impls` (Rust trait — requires
       trait-focused query when ``query`` is supplied).
    2. :attr:`GroupingRules.dataclass_methods` (Python
       ``@dataclass``).
    3. :attr:`GroupingRules.test_subject` (any language, ``test_``
       / ``Test`` prefix).
    4. :attr:`GroupingRules.function_type_aliases` (Python
       function / method).

    ``query`` is consulted for the trait rule only: the trait's
    name MUST appear in ``query.symbol_names`` for the impls to
    be pulled in. Passing ``query=None`` treats every trait as
    trait-focused (the pure API path; caller-supplied narrowing).
    """
    out: list[SymbolGroup] = []
    for symbol in symbols:
        language = (symbol.language or "").lower()
        if rules.languages and language and language not in rules.languages:
            out.append(SymbolGroup(primary=symbol))
            continue

        # Rule 1: Rust trait + impls
        if rules.trait_impls and _looks_like_trait(symbol):
            if _is_trait_focused(query, symbol):
                companions = _find_trait_impls(symbol, index)
                out.append(
                    SymbolGroup(
                        primary=symbol,
                        companions=tuple(companions),
                        rule=RULE_TRAIT_IMPLS,
                    )
                )
                continue

        # Rule 2: Python dataclass + methods
        if rules.dataclass_methods and _looks_like_dataclass(symbol):
            companions = _find_dataclass_methods(symbol, index)
            out.append(
                SymbolGroup(
                    primary=symbol,
                    companions=tuple(companions),
                    rule=RULE_DATACLASS_METHODS,
                )
            )
            continue

        # Rule 3: test → subject
        if rules.test_subject:
            matches, _subject_name, _subject_kind = _looks_like_test(symbol)
            if matches:
                companions = _find_test_subject(symbol, index)
                out.append(
                    SymbolGroup(
                        primary=symbol,
                        companions=tuple(companions),
                        rule=RULE_TEST_SUBJECT,
                    )
                )
                continue

        # Rule 4: Python function + type aliases
        if rules.function_type_aliases and _looks_like_function_for_type_aliases(
            symbol
        ):
            companions = _find_function_type_aliases(symbol, index)
            out.append(
                SymbolGroup(
                    primary=symbol,
                    companions=tuple(companions),
                    rule=RULE_FUNCTION_TYPE_ALIASES,
                )
            )
            continue

        # No rule fired — primary-only group.
        out.append(SymbolGroup(primary=symbol))
    return out


def _is_trait_focused(query: Any | None, trait: SymbolRow) -> bool:
    """Return True when ``query`` names ``trait`` in ``symbol_names``.

    When ``query`` is ``None`` the pure API returns True (a caller
    who does not supply a query is asking the grouping surface to
    fire unconditionally). When ``query`` carries a ``symbol_names``
    field, the trait's name must appear in it; a query focused on
    the concrete impl type does NOT drag the trait's siblings in.
    """
    if query is None:
        return True
    symbol_names = getattr(query, "symbol_names", None)
    if not symbol_names:
        # A query with no explicit symbol_names (all keyword /
        # graph-seeded) is treated as trait-neutral; the trait
        # surfaced through keyword/graph deserves its impls.
        return True
    return trait.name in symbol_names


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------


_CONFIG_RELATIVE_PATH = Path(".ract") / "grouping_rules.yaml"


def load_grouping_rules(workspace_root: str | Path) -> GroupingRules:
    """Load :class:`GroupingRules` from
    ``<workspace_root>/.ract/grouping_rules.yaml``.

    Missing file → return the shipped defaults. Missing or
    malformed keys → the corresponding default fills in (partial
    overrides are supported). A file whose top-level shape is not a
    mapping raises :class:`ValueError` — a silent fallback would
    mask a project-wide config typo.

    The YAML schema (matches the shipped
    ``.ract/grouping_rules.yaml`` example):

    .. code-block:: yaml

        grouping:
          dataclass_methods: true
          trait_impls: true
          test_subject: true
          function_type_aliases: true
          languages: [python, typescript, rust, go]
    """
    root = Path(workspace_root)
    path = root / _CONFIG_RELATIVE_PATH
    if not path.exists():
        return GroupingRules()
    try:
        # Local import: yaml is already a shipped dep (ract.yaml,
        # budget config) so no new dep here.
        import yaml  # type: ignore
    except ImportError:  # pragma: no cover - PyYAML is a shipped dep
        return GroupingRules()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - yaml parse error
        raise ValueError(
            f"load_grouping_rules: failed to parse {path}: {exc}"
        ) from exc
    if raw is None:
        return GroupingRules()
    if not isinstance(raw, dict):
        raise ValueError(
            f"load_grouping_rules: top-level shape must be a mapping; "
            f"got {type(raw).__name__} at {path}"
        )
    section = raw.get("grouping", {})
    if section in (None, {}):
        return GroupingRules()
    if not isinstance(section, dict):
        raise ValueError(
            f"load_grouping_rules: 'grouping' key must be a mapping; "
            f"got {type(section).__name__} at {path}"
        )
    defaults = GroupingRules()
    languages_raw = section.get("languages", None)
    if languages_raw is None:
        languages = defaults.languages
    else:
        if not isinstance(languages_raw, (list, tuple, set, frozenset)):
            raise ValueError(
                f"load_grouping_rules: 'languages' must be a sequence; "
                f"got {type(languages_raw).__name__}"
            )
        languages = frozenset(str(lang).lower() for lang in languages_raw)
    return GroupingRules(
        dataclass_methods=bool(
            section.get("dataclass_methods", defaults.dataclass_methods)
        ),
        trait_impls=bool(section.get("trait_impls", defaults.trait_impls)),
        test_subject=bool(section.get("test_subject", defaults.test_subject)),
        function_type_aliases=bool(
            section.get("function_type_aliases", defaults.function_type_aliases)
        ),
        languages=languages,
    )


__all__ = [
    "GroupingRules",
    "LEGAL_RULES",
    "RULE_DATACLASS_METHODS",
    "RULE_FUNCTION_TYPE_ALIASES",
    "RULE_NONE",
    "RULE_TEST_SUBJECT",
    "RULE_TRAIT_IMPLS",
    "SymbolGroup",
    "group_symbols",
    "load_grouping_rules",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.1

"""ALM Gate G5 — sandbox-enforced test integrity via AST diff.

The reward channel is the visible acceptance suite. If the sandboxed
model can silently mutate the suite (net-new ``pytest.skip``, deleted
assertions, edits to the grader module), the whole gate stack becomes
theatre. G5 attaches at the pre-commit worktree gate: any diff hitting
a denied AST pattern rolls back at the merge site so the write never
lands on the parent snapshot.

Detection is per-language. Python ships in this module using the
standard library ``ast`` module; extension points for TypeScript, Go,
and Rust are declared but stub-implemented (log-only) so the graph is
at least populated with Python coverage on mixed-language workspaces
(lateral chain branch D from module_03). See Flagged gaps for the
v0.5 tree-sitter backlog.

Reference sources:

- Python ``ast`` module (public standard-library documentation).
- METR reward-hacking findings on grader monkey-patching and test-suite
  editing to make a run appear passing.
- ALM spec §3.5 (Gate G5); §13 signal 5.

Design rationale in ``docs/ADRs/ADR-0021-antilazy-test-integrity-and-
under-edit.md``.
"""

from __future__ import annotations

import ast
import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ract.security.manifest import TestIntegrityConfig, default_test_integrity_config

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


TestFileLanguage = Literal["python", "typescript", "go", "rust", "unknown"]

# Test-file extension heuristics per language. A file is treated as a
# test file when its path either matches ``tests/**`` or when its
# basename starts with ``test_`` / ends with ``_test`` (idiomatic
# across the four supported languages).
_LANGUAGE_EXTENSIONS: dict[str, TestFileLanguage] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".go": "go",
    ".rs": "rust",
}


def _language_for(path: str) -> TestFileLanguage:
    for ext, lang in _LANGUAGE_EXTENSIONS.items():
        if path.endswith(ext):
            return lang
    return "unknown"


def _is_test_file(path: str) -> bool:
    """Heuristic: does ``path`` look like a test file worth analyzing?"""
    p = path.replace("\\", "/")
    if "/tests/" in p or p.startswith("tests/") or "/test/" in p:
        return True
    name = p.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


# ---------------------------------------------------------------------------
# Violation report
# ---------------------------------------------------------------------------


ViolationSeverity = Literal["hard_block", "advisory"]


@dataclass(frozen=True)
class TestIntegrityViolation:
    """One AST-level test-integrity violation detected in a diff.

    The ``__test__ = False`` marker keeps pytest from trying to
    collect this class as a test case on account of the ``Test`` prefix.
    """

    __test__ = False

    pattern: str
    file: str
    line: int = 0
    severity: ViolationSeverity = "hard_block"
    handshake_allowed: bool = True
    detail: str = ""

    def to_canonical(self) -> dict[str, object]:
        return {
            "pattern": self.pattern,
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "handshake_allowed": self.handshake_allowed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TestIntegrityReport:
    """Aggregate report over one ``analyze_diff`` invocation."""

    __test__ = False

    violations: tuple[TestIntegrityViolation, ...] = field(default_factory=tuple)
    unsupported_files: tuple[str, ...] = field(default_factory=tuple)
    files_analyzed: tuple[str, ...] = field(default_factory=tuple)
    handshake_approved: bool = False

    def hard_block_violations(self) -> tuple[TestIntegrityViolation, ...]:
        return tuple(v for v in self.violations if v.severity == "hard_block")

    def advisory_violations(self) -> tuple[TestIntegrityViolation, ...]:
        return tuple(v for v in self.violations if v.severity == "advisory")

    def passed(self) -> bool:
        """A report passes iff no hard-block violation survives the handshake filter."""
        for v in self.violations:
            if v.severity != "hard_block":
                continue
            if self.handshake_approved and v.handshake_allowed:
                continue
            return False
        return True

    def to_canonical(self) -> dict[str, object]:
        return {
            "violations": [v.to_canonical() for v in self.violations],
            "unsupported_files": list(self.unsupported_files),
            "files_analyzed": list(self.files_analyzed),
            "handshake_approved": self.handshake_approved,
        }


# ---------------------------------------------------------------------------
# Rule primitive (per plan step 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestIntegrityRule:
    """One denied pattern with its severity and handshake policy."""

    __test__ = False

    pattern: str
    severity: ViolationSeverity = "hard_block"
    handshake_allowed: bool = True


# ---------------------------------------------------------------------------
# AST diff — Python (concrete)
# ---------------------------------------------------------------------------


# Patterns from ALM §3.5 — canonical strings the violations carry as
# ``pattern`` so the trace channel is a stable enum.
PATTERN_PYTEST_SKIP: str = "pytest.skip"
PATTERN_PYTEST_XFAIL: str = "pytest.xfail"
PATTERN_MARK_SKIP: str = "pytest.mark.skip"
PATTERN_MARK_SKIPIF: str = "pytest.mark.skipif"
PATTERN_MARK_XFAIL: str = "pytest.mark.xfail"
PATTERN_ASSERTION_REMOVAL: str = "assertion_removal"
PATTERN_ASSERT_TRUE_TO_PASS: str = "assert_true_to_pass"
PATTERN_DENIED_FILE_EDIT: str = "denied_file_edit"
PATTERN_MONKEY_PATCH: str = "monkey_patch"
PATTERN_UNSUPPORTED_LANGUAGE: str = "test_integrity_unsupported_language"

# Reviewer-facing metaprogramming-escape patterns. The AST analyzer
# below detects the shapes that produce a ``pytest.skip`` (or any
# other denied call) without the literal attribute access, and lands
# them under this pattern rather than under the specific-call name so
# the trace channel discriminates escapes from direct calls.
PATTERN_METAPROG_ESCAPE: str = "test_integrity_metaprogramming_escape"


def _iter_calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _iter_decorators(tree: ast.AST) -> list[tuple[ast.expr, ast.AST]]:
    """Return every (decorator, host_node) pair in ``tree``.

    Host node is the ``FunctionDef`` / ``AsyncFunctionDef`` /
    ``ClassDef`` the decorator is attached to; the caller uses it to
    compute line numbers for the violation payload.
    """
    pairs: list[tuple[ast.expr, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in node.decorator_list:
                pairs.append((deco, node))
    return pairs


def _call_attribute_chain(node: ast.expr) -> str:
    """Return the dotted-attribute string for ``node`` or ''."""
    parts: list[str] = []
    cur: ast.expr | None = node
    while cur is not None:
        if isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        elif isinstance(cur, ast.Name):
            parts.append(cur.id)
            cur = None
        else:
            return ""
    return ".".join(reversed(parts))


def _decorator_attribute_chain(deco: ast.expr) -> str:
    """Return the dotted chain for a decorator (call or attribute)."""
    if isinstance(deco, ast.Call):
        return _call_attribute_chain(deco.func)
    return _call_attribute_chain(deco)


def _test_functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return the ``test_*`` functions in ``tree`` keyed by qualified name."""
    result: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name.startswith("test_") or node.name == "test"
        ):
            result[node.name] = node
    return result


def _asserts_in(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.Assert))


def _assert_body_contains_only_true(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True iff every ``assert`` in ``fn`` is a trivial ``assert True``."""
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    if not asserts:
        return False
    for a in asserts:
        test = a.test
        if isinstance(test, ast.Constant) and test.value is True:
            continue
        return False
    return True


def _skip_call_is_platform_exempt(
    call: ast.Call, allowed_reason_substrings: tuple[str, ...]
) -> bool:
    """Return True if a ``pytest.skip(...)`` call is a legitimate portability skip.

    Lateral chain branch A: Windows-only tests marked
    ``pytest.skip`` on Linux are portability, not test-hacking. The
    exemption fires when the call's ``reason`` kwarg (or first positional
    arg) matches one of the allowed substrings, or when a ``sys.platform``
    expression appears anywhere inside the call arguments.
    """
    for kw in call.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
            text = str(kw.value.value).lower()
            for allowed in allowed_reason_substrings:
                if allowed.lower() in text:
                    return True
    if call.args and isinstance(call.args[0], ast.Constant):
        text = str(call.args[0].value).lower()
        for allowed in allowed_reason_substrings:
            if allowed.lower() in text:
                return True
    # sys.platform / platform.system references inside the arguments
    for sub in ast.walk(call):
        if isinstance(sub, ast.Attribute):
            chain = _call_attribute_chain(sub)
            if chain in ("sys.platform", "platform.system"):
                return True
    return False


def _skipif_is_platform_exempt(deco: ast.expr) -> bool:
    """Return True if a ``@pytest.mark.skipif(...)`` decorator is platform-based."""
    if not isinstance(deco, ast.Call):
        return False
    for sub in ast.walk(deco):
        if isinstance(sub, ast.Attribute):
            chain = _call_attribute_chain(sub)
            if chain in ("sys.platform", "platform.system"):
                return True
    return False


def _call_target_name_for_escape(func: ast.expr) -> str:
    """Best-effort name resolver used only by the escape detector."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _detect_metaprogramming_escape(
    tree: ast.AST, watch: tuple[str, ...]
) -> list[tuple[str, int]]:
    """Return (call_target, line) pairs where a denied call was constructed
    through metaprogramming.

    Second Pass adversarial question 1: a model can bypass a literal
    ``pytest.skip`` denial by calling ``getattr(pytest, 'skip')()``,
    ``pytest.__dict__['skip']()``, ``exec("pytest.skip()")``, or by
    obtaining the module via ``importlib.import_module('pytest').skip()``
    or ``type(pytest).__getattribute__(pytest, 'skip')()``. This
    detector walks the tree for the known metaprogramming shapes and
    reports a match when the constant argument names any watched
    symbol.

    Note: static analysis cannot catch data-flow shapes like
    ``s = pytest.skip; s()`` (they need a def-use walk); those are
    logged as v0.5 backlog in Flagged gaps.
    """
    escapes: list[tuple[str, int]] = []
    watch_set = set(watch)
    for node in ast.walk(tree):
        # getattr(pytest, "skip") / getattr(pytest, "xfail") / ...
        if isinstance(node, ast.Call):
            func_chain = _call_attribute_chain(node.func)
            if func_chain == "getattr" and len(node.args) >= 2:
                target = node.args[0]
                name_arg = node.args[1]
                if (
                    isinstance(target, ast.Name)
                    and isinstance(name_arg, ast.Constant)
                    and isinstance(name_arg.value, str)
                ):
                    ident = f"{target.id}.{name_arg.value}"
                    if ident in watch_set:
                        escapes.append((ident, node.lineno))
            # exec("pytest.skip()") / eval(...)
            if func_chain in ("exec", "eval") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    for w in watch_set:
                        if w in first.value:
                            escapes.append((w, node.lineno))
                            break
            # type(pytest).__getattribute__(pytest, "skip") — the outer
            # Attribute's value is itself a Call ``type(x)``; the
            # attribute chain helper returns "" for that shape because
            # its base is a Call rather than a Name.
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "__getattribute__"
                and isinstance(node.func.value, ast.Call)
                and _call_target_name_for_escape(node.func.value.func) == "type"
                and len(node.args) >= 2
            ):
                obj_arg = node.args[0]
                name_arg = node.args[1]
                if (
                    isinstance(obj_arg, ast.Name)
                    and isinstance(name_arg, ast.Constant)
                    and isinstance(name_arg.value, str)
                ):
                    ident = f"{obj_arg.id}.{name_arg.value}"
                    if ident in watch_set:
                        escapes.append((ident, node.lineno))
        # pytest.__dict__["skip"]() shape via Subscript
        if isinstance(node, ast.Subscript):
            chain = _call_attribute_chain(node.value)
            if chain and chain.endswith(".__dict__"):
                base = chain[: -len(".__dict__")]
                slc = node.slice
                if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
                    ident = f"{base}.{slc.value}"
                    if ident in watch_set:
                        escapes.append((ident, node.lineno))
        # importlib.import_module("pytest").skip() shape.
        # Second Pass Q1 (Cycle-2 fix): the outer Attribute's ``value``
        # is a Call whose func chain is ``importlib.import_module`` (or
        # ``import_module``) with a string arg — that string names the
        # module the outer attribute reaches into.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            outer_attr = node.func
            inner = outer_attr.value
            if isinstance(inner, ast.Call):
                inner_chain = _call_attribute_chain(inner.func)
                if inner_chain in ("importlib.import_module", "import_module") and (
                    inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and isinstance(inner.args[0].value, str)
                ):
                    ident = f"{inner.args[0].value}.{outer_attr.attr}"
                    if ident in watch_set:
                        escapes.append((ident, node.lineno))
    return escapes


def analyze_diff_python(
    file_path: str,
    parent_source: str | None,
    child_source: str | None,
    config: TestIntegrityConfig,
) -> list[TestIntegrityViolation]:
    """Concrete AST-diff analyzer for a single Python test file.

    ``parent_source`` may be ``None`` if the file is new in the child;
    ``child_source`` may be ``None`` if the file was deleted (a rare
    but valid diff shape). Returns the list of violations for this
    file.
    """
    violations: list[TestIntegrityViolation] = []

    # File deletion — surface it if the file matches a denied glob but
    # otherwise let normal cleanup pass (a test file being removed is
    # not by itself a hack; the mutation-kill gate covers that).
    if child_source is None:
        for glob in config.denied_file_edits:
            if fnmatch.fnmatchcase(file_path, glob):
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_DENIED_FILE_EDIT,
                        file=file_path,
                        line=0,
                        detail=f"deleted file matches denied glob {glob!r}",
                    )
                )
        return violations

    # Denied-file edits win regardless of AST content — the pattern is
    # "this file must not be modified", not "the modification must be
    # semantically bad".
    if parent_source != child_source:
        for glob in config.denied_file_edits:
            if fnmatch.fnmatchcase(file_path, glob):
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_DENIED_FILE_EDIT,
                        file=file_path,
                        line=0,
                        detail=f"edit to file matches denied glob {glob!r}",
                    )
                )

    try:
        child_tree = ast.parse(child_source, filename=file_path)
    except SyntaxError:
        # Cannot parse the child — the sandbox already rejects invalid
        # Python at compile time; leave a marker so the diff is not
        # silently accepted.
        violations.append(
            TestIntegrityViolation(
                pattern=PATTERN_UNSUPPORTED_LANGUAGE,
                file=file_path,
                severity="advisory",
                handshake_allowed=False,
                detail="child source is not parseable Python",
            )
        )
        return violations

    parent_tree: ast.AST | None = None
    if parent_source is not None:
        try:
            parent_tree = ast.parse(parent_source, filename=file_path)
        except SyntaxError:
            parent_tree = None  # treat as new file for the diff

    # ---- net-new pytest.skip / pytest.xfail calls
    parent_calls_by_chain: dict[str, int] = {}
    if parent_tree is not None:
        for call in _iter_calls(parent_tree):
            chain = _call_attribute_chain(call.func)
            if chain:
                parent_calls_by_chain[chain] = parent_calls_by_chain.get(chain, 0) + 1
    child_calls: list[tuple[str, ast.Call]] = []
    for call in _iter_calls(child_tree):
        chain = _call_attribute_chain(call.func)
        if chain:
            child_calls.append((chain, call))

    # Count child occurrences net of parent counts; net-new occurrences
    # are those exceeding the parent count.
    child_counts: dict[str, list[ast.Call]] = {}
    for chain, call in child_calls:
        child_counts.setdefault(chain, []).append(call)

    denied_calls = set(config.denied_ast_patterns) | {
        PATTERN_PYTEST_SKIP,
        PATTERN_PYTEST_XFAIL,
    }
    for chain, calls in child_counts.items():
        if chain not in denied_calls:
            continue
        parent_n = parent_calls_by_chain.get(chain, 0)
        for call in calls[parent_n:]:  # net-new tail
            if chain == PATTERN_PYTEST_SKIP and _skip_call_is_platform_exempt(
                call, config.allowed_skip_reason_substrings
            ):
                continue
            violations.append(
                TestIntegrityViolation(
                    pattern=chain,
                    file=file_path,
                    line=call.lineno,
                    detail="net-new call to a denied test-integrity target",
                )
            )

    # ---- net-new denied decorators
    parent_decos: dict[str, int] = {}
    if parent_tree is not None:
        for deco, _host in _iter_decorators(parent_tree):
            chain = _decorator_attribute_chain(deco)
            if chain:
                parent_decos[chain] = parent_decos.get(chain, 0) + 1
    child_decos: dict[str, list[tuple[ast.expr, ast.AST]]] = {}
    for deco, host in _iter_decorators(child_tree):
        chain = _decorator_attribute_chain(deco)
        if chain:
            child_decos.setdefault(chain, []).append((deco, host))

    denied_decos = {
        PATTERN_MARK_SKIP,
        PATTERN_MARK_SKIPIF,
        PATTERN_MARK_XFAIL,
    } | set(config.denied_ast_patterns)
    for chain, entries in child_decos.items():
        if chain not in denied_decos:
            continue
        parent_n = parent_decos.get(chain, 0)
        for deco, host in entries[parent_n:]:
            if chain == PATTERN_MARK_SKIPIF and _skipif_is_platform_exempt(deco):
                continue
            violations.append(
                TestIntegrityViolation(
                    pattern=chain,
                    file=file_path,
                    line=getattr(deco, "lineno", getattr(host, "lineno", 0)),
                    detail="net-new denied decorator on a test host",
                )
            )

    # ---- assertion removal / assert-True-to-pass inside existing tests
    if parent_tree is not None:
        parent_fns = _test_functions(parent_tree)
        child_fns = _test_functions(child_tree)
        for name, parent_fn in parent_fns.items():
            child_fn = child_fns.get(name)
            if child_fn is None:
                # A whole test was deleted — the mutation-kill gate
                # handles the coverage loss; here we mark it as a
                # denied assertion transform so the pattern is visible.
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_ASSERTION_REMOVAL,
                        file=file_path,
                        line=parent_fn.lineno,
                        detail=f"existing test {name!r} was removed",
                    )
                )
                continue
            parent_asserts = _asserts_in(parent_fn)
            child_asserts = _asserts_in(child_fn)
            if child_asserts < parent_asserts:
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_ASSERTION_REMOVAL,
                        file=file_path,
                        line=child_fn.lineno,
                        detail=(
                            f"asserts in {name!r} dropped from "
                            f"{parent_asserts} to {child_asserts}"
                        ),
                    )
                )
            elif (
                parent_asserts > 0
                and not _assert_body_contains_only_true(parent_fn)
                and _assert_body_contains_only_true(child_fn)
            ):
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_ASSERT_TRUE_TO_PASS,
                        file=file_path,
                        line=child_fn.lineno,
                        detail=(
                            f"asserts in {name!r} rewritten to trivial "
                            "assert True (assertion transform)"
                        ),
                    )
                )

    # ---- monkey-patch watchlist (sys.modules['<x>'] = ..., builtins.__import__ = ...)
    watch = set(config.monkey_patch_watchlist)
    parent_targets: set[str] = set()
    if parent_tree is not None:
        for node in ast.walk(parent_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    tgt_repr = _assign_target_repr(target)
                    if tgt_repr:
                        parent_targets.add(tgt_repr)
    for node in ast.walk(child_tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                tgt_repr = _assign_target_repr(target)
                if not tgt_repr:
                    continue
                if tgt_repr in watch and tgt_repr not in parent_targets:
                    violations.append(
                        TestIntegrityViolation(
                            pattern=PATTERN_MONKEY_PATCH,
                            file=file_path,
                            line=node.lineno,
                            detail=f"net-new monkey-patch of watched target {tgt_repr!r}",
                        )
                    )

    # ---- metaprogramming escape detection (Second Pass Q1)
    parent_escapes: set[tuple[str, int]] = set()
    if parent_tree is not None:
        parent_escapes = set(
            _detect_metaprogramming_escape(parent_tree, tuple(denied_calls))
        )
    child_escapes = _detect_metaprogramming_escape(child_tree, tuple(denied_calls))
    for ident, lineno in child_escapes:
        # Any escape that was not already in the parent counts as
        # net-new. We compare only by identity, not line, so an escape
        # that moved lines is still detected as pre-existing.
        if any(pi == ident for pi, _ in parent_escapes):
            continue
        violations.append(
            TestIntegrityViolation(
                pattern=PATTERN_METAPROG_ESCAPE,
                file=file_path,
                line=lineno,
                detail=(
                    f"denied target {ident!r} constructed via "
                    "getattr/__dict__/exec metaprogramming; "
                    "AST-literal denial bypassed"
                ),
            )
        )

    return violations


def _assign_target_repr(target: ast.expr) -> str:
    """Return a canonical dotted / subscript string for an assignment target.

    ``sys.modules['x']`` → ``"sys.modules['x']"``.
    ``builtins.__import__`` → ``"builtins.__import__"``.
    Names and attributes without brackets fall through unchanged.
    """
    if isinstance(target, ast.Subscript):
        base = _call_attribute_chain(target.value)
        if base and isinstance(target.slice, ast.Constant):
            return f"{base}[{target.slice.value!r}]"
        return ""
    return _call_attribute_chain(target)


# ---------------------------------------------------------------------------
# Public analyze_diff — dispatches to per-language backend
# ---------------------------------------------------------------------------


def analyze_diff(
    parent_snapshot: "WorkspaceSnapshot",
    child_snapshot: "WorkspaceSnapshot",
    config: TestIntegrityConfig | None = None,
    *,
    handshake_approved: bool = False,
) -> TestIntegrityReport:
    """Return the ``TestIntegrityReport`` for the diff between snapshots.

    Iterates the union of files touched by the diff (present in either
    snapshot with differing contents, or newly-present in the child).
    Python test files are analyzed by ``analyze_diff_python``; other
    languages emit a ``test_integrity_unsupported_language`` advisory
    (lateral chain branch D) so the coverage gap is visible in the
    trace rather than silent.
    """
    if config is None:
        config = default_test_integrity_config()

    all_paths = set(parent_snapshot.files.keys()) | set(child_snapshot.files.keys())
    changed = sorted(
        p
        for p in all_paths
        if parent_snapshot.files.get(p) != child_snapshot.files.get(p)
    )

    violations: list[TestIntegrityViolation] = []
    unsupported: list[str] = []
    analyzed: list[str] = []

    for path in changed:
        parent_source = parent_snapshot.files.get(path)
        child_source = child_snapshot.files.get(path)

        # Denied-file edits also cover non-test files (e.g. `tests/**/
        # grader.py` or a conftest); the denied-file check runs
        # regardless of language.
        for glob in config.denied_file_edits:
            if fnmatch.fnmatchcase(path, glob):
                violations.append(
                    TestIntegrityViolation(
                        pattern=PATTERN_DENIED_FILE_EDIT,
                        file=path,
                        line=0,
                        detail=f"edit to file matches denied glob {glob!r}",
                    )
                )

        if not _is_test_file(path):
            continue

        lang = _language_for(path)
        if lang == "python":
            analyzed.append(path)
            violations.extend(
                analyze_diff_python(path, parent_source, child_source, config)
            )
        elif lang == "unknown":
            # Not a language we know about; skip silently.
            continue
        else:
            unsupported.append(path)
            violations.append(
                TestIntegrityViolation(
                    pattern=PATTERN_UNSUPPORTED_LANGUAGE,
                    file=path,
                    severity="advisory",
                    handshake_allowed=False,
                    detail=(
                        f"test file in language {lang!r} not yet analyzed by G5; "
                        "v0.5 tree-sitter backlog. Advisory logged; run continues."
                    ),
                )
            )

    # Deduplicate identical violations (same pattern + file + line).
    seen: set[tuple[str, str, int, str]] = set()
    deduped: list[TestIntegrityViolation] = []
    for v in violations:
        key = (v.pattern, v.file, v.line, v.severity)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)

    return TestIntegrityReport(
        violations=tuple(deduped),
        unsupported_files=tuple(unsupported),
        files_analyzed=tuple(analyzed),
        handshake_approved=handshake_approved,
    )


# ---------------------------------------------------------------------------
# On-disk snapshot writer for evals/runs/<run_id>/test_integrity.json
# ---------------------------------------------------------------------------


def write_test_integrity_snapshot(run_dir: Path, report: TestIntegrityReport) -> Path:
    """Persist the report to ``<run_dir>/test_integrity.json``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "test_integrity.json"
    path.write_text(
        json.dumps(report.to_canonical(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# RACT 0.4.0

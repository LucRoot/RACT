"""Architecture gate: no ``.rack/`` string literals outside the migration shim.

v0.5.1 wiring module_10 (Lens A C2) unified workspace state on ``.ract/``.
Every code path that reads / writes workspace state must use the canonical
directory. Legitimate references to ``.rack/`` are limited to:

- :mod:`ract.workspace_state` -- the migration shim itself owns the
  legacy directory name as a string constant.
- ``src/ract/core/intent_recompile.py`` -- the ``skip_dirs`` set that
  filters both ``.rack`` (legacy) and ``.ract`` (canonical) from the
  workspace snapshot walker. Keeping the legacy entry keeps pre-
  migration workspaces from tripping the snapshot on stale state.
- Python comments (a line whose non-whitespace prefix is ``#``).
- Python docstrings (the first statement of a module / class / function
  when that statement is a bare string constant).

Any other occurrence -- most importantly, any string literal used as a
:class:`pathlib.Path` argument or an I/O call arg -- is a wiring gap.

SP Q9 [DEFECT] amendment (external reviewer): the pre-amendment version
of this gate used a substring heuristic (``CONTEXT_MARKERS = ("legacy",
"migration", "was ", ...)``) that would allow a line like::

    # TODO: migrate legacy .rack/new_feature  # migration
    os.makedirs(".rack/new_feature")

to pass because the comment on the SAME line contained the marker
substrings. The amendment replaces the substring heuristic with a
strict two-part check:

1. AST walk over all string constants -- if the string value contains
   ``.rack`` AND is not a docstring, flag it.
2. Line-by-line walk over the raw source -- if a non-string line
   (i.e., outside triple-quoted contexts, verified by AST tokenize
   pass) contains ``.rack`` AND is not a comment (does not start with
   ``#``), flag it.

Together the two checks refuse the reviewer's escape-hatch example
while allowing legitimate docstring / comment references.
"""

from __future__ import annotations

import ast
import re
import tokenize
from io import StringIO
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ract"

# Files that legitimately mention ``.rack`` in production code paths
# (see module docstring above).
ALLOWED_FILES = {
    SRC_ROOT / "workspace_state.py",
    SRC_ROOT / "core" / "intent_recompile.py",
}

_RACK_PATTERN = re.compile(r"\.rack\b")


def _collect_docstring_nodes(tree: ast.AST) -> set[int]:
    """Return the id() of every AST node that is a docstring (first stmt).

    A docstring is: the first statement of Module / FunctionDef /
    AsyncFunctionDef / ClassDef when that first statement is an
    :class:`ast.Expr` wrapping a :class:`ast.Constant` string.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _string_violations(source: str, py_file: Path) -> list[str]:
    """Return AST-level violations: string constants containing ``.rack``.

    Docstrings are tolerated (they document behavior); every other
    string literal is flagged.
    """
    tree = ast.parse(source, filename=str(py_file))
    docstring_ids = _collect_docstring_nodes(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if not _RACK_PATTERN.search(node.value):
            continue
        if id(node) in docstring_ids:
            continue
        lineno = getattr(node, "lineno", "?")
        try:
            loc = py_file.relative_to(SRC_ROOT.parent.parent)
        except ValueError:
            loc = py_file
        violations.append(
            f"{loc}:{lineno}: "
            f"string literal containing .rack outside docstring: {node.value!r}"
        )
    return violations


def _comment_violations(source: str, py_file: Path) -> list[str]:
    """Return line-based violations that AST cannot catch.

    Comments are tolerated (they document behavior); every non-string
    non-comment line with ``.rack`` is flagged. Comments and string
    tokens are identified via :mod:`tokenize` so triple-quoted docstrings
    (already counted by AST) are not double-flagged.
    """
    violations: list[str] = []
    covered_lines: set[int] = set()
    try:
        tokens = list(tokenize.generate_tokens(StringIO(source).readline))
    except tokenize.TokenizeError:
        return violations
    for tok in tokens:
        if tok.type not in {tokenize.COMMENT, tokenize.STRING}:
            continue
        # Track every source line covered by comments / strings; these
        # were already vetted by the AST pass or by comment tolerance.
        start_line = tok.start[0]
        end_line = tok.end[0]
        for i in range(start_line, end_line + 1):
            covered_lines.add(i)
    for i, line in enumerate(source.splitlines(), start=1):
        if not _RACK_PATTERN.search(line):
            continue
        if i in covered_lines:
            continue
        # A non-comment / non-string line with ``.rack`` -- a real code
        # reference. Flag it.
        try:
            loc = py_file.relative_to(SRC_ROOT.parent.parent)
        except ValueError:
            loc = py_file
        violations.append(f"{loc}:{i}: {line.strip()}")
    return violations


def test_no_rack_literal_outside_migration_shim() -> None:
    """No ``.rack`` reference outside allow-list + docstrings + comments."""
    violations: list[str] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file in ALLOWED_FILES:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not _RACK_PATTERN.search(text):
            continue
        violations.extend(_string_violations(text, py_file))
        violations.extend(_comment_violations(text, py_file))
    assert not violations, (
        "unmigrated `.rack` references in src/ract/ (v0.5.1 module_10 "
        "Lens A C2 gate; SP Q9 [DEFECT] hardened):\n" + "\n".join(violations)
    )


def test_workspace_state_dir_constant_is_ract() -> None:
    """The canonical directory constant is ``.ract`` -- guards against typo drift."""
    from ract.workspace_state import LEGACY_STATE_DIR_NAME, WORKSPACE_STATE_DIR_NAME

    assert WORKSPACE_STATE_DIR_NAME == ".ract"
    assert LEGACY_STATE_DIR_NAME == ".rack"


def test_migration_shim_warns_loudly_when_both_dirs_present(
    tmp_path: Path, capsys
) -> None:
    """SP Q2 [PARTIAL] amendment: BOTH-exist path emits stderr diagnostic.

    A silent WARN log is easy to miss in noisy CI; the amendment adds
    an ALLCAPS stderr one-liner so shell / CI operators notice the
    workspace-state divergence immediately.
    """
    from ract.workspace_state import migrate_rack_to_ract

    (tmp_path / ".ract").mkdir()
    (tmp_path / ".rack").mkdir()

    outcome = migrate_rack_to_ract(tmp_path)
    assert outcome == "warned_both"
    captured = capsys.readouterr()
    assert "WARN" in captured.err, (
        "Q2 [PARTIAL] amendment: BOTH-exist branch must emit an "
        "ALLCAPS stderr diagnostic so operators see it"
    )
    # Neither directory was deleted / renamed.
    assert (tmp_path / ".ract").is_dir()
    assert (tmp_path / ".rack").is_dir()


def test_gate_rejects_reviewer_escape_hatch(tmp_path: Path) -> None:
    """SP Q9 [DEFECT] amendment regression: the reviewer's example fails.

    Prior heuristic tolerated a line whose comment contained ``legacy``
    or ``migration`` even when the code on that line executed a real
    ``.rack/`` write. This synthesises the example and asserts the
    hardened gate rejects it.
    """
    fake_file = tmp_path / "fake_module.py"
    fake_file.write_text(
        "import os\n"
        "# TODO: migrate legacy code to use .rack/new_feature  # migration\n"
        "os.makedirs('.rack/new_feature')\n",
        encoding="utf-8",
    )
    text = fake_file.read_text(encoding="utf-8")
    violations = _string_violations(text, fake_file) + _comment_violations(
        text, fake_file
    )
    # The string literal in os.makedirs('.rack/new_feature') is the
    # real code reference; must be flagged.
    assert any("os.makedirs" in v or "new_feature" in v for v in violations), (
        f"escape hatch not flagged; violations were: {violations}"
    )


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C2 regression; SP Q9 hardened)

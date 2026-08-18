"""Public provenance statement + independence lint.

Asserts that ``docs/PROVENANCE.md`` exists, is concise, names the real
provenance symbols, and that no source file under ``src/ract/`` imports from
a private or internal package. This is the load-bearing independence claim:
if a forbidden import appears, the public statement is false and the build
must fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SRC_DIR = REPO_ROOT / "src" / "ract"
PROVENANCE_DOC = DOCS_DIR / "PROVENANCE.md"

# Roots that may legitimately appear in src/ract imports. Everything else is
# treated as a forbidden (private/internal/undeclared) dependency. This list
# mirrors the declared dependencies in pyproject.toml plus the stdlib modules
# the package actually uses. It is intentionally maintained by hand so that
# adding a new third-party dep is a conscious, reviewed act.
ALLOWED_IMPORT_ROOTS = {
    # first-party
    "ract",
    # declared third-party (pyproject.toml [project].dependencies + [dev])
    "yaml",
    "httpx",
    "zstandard",
    "rich",
    "cryptography",
    # module_05 (ADR-0015): OpenTelemetry API/SDK/OTLP-HTTP exporter is
    # a runtime dep for the event-trace substrate. Imported lazily
    # inside ``ract.trace.otel``; declared in pyproject.toml.
    "opentelemetry",
    # threading is stdlib; the writer uses a Lock for the
    # single-writer-per-run contract (see writer.py docstring).
    "threading",
    # dev-only libs that some modules import for optional features
    "pytest",
    "pydantic",
    "fastapi",
    "email_validator",
    "hypothesis",
    "respx",
    # future annotations + stdlib actually used by the package
    "__future__",
    "typing",
    "dataclasses",
    "pathlib",
    "json",
    "re",
    "subprocess",
    "sys",
    "collections",
    "os",
    "datetime",
    "ast",
    "hashlib",
    "argparse",
    "time",
    "shutil",
    "enum",
    "difflib",
    "abc",
    "tempfile",
    "concurrent",
    "math",
    "tokenize",
    "uuid",
    "string",
    "statistics",
    "io",
    "importlib",
    "logging",
    "builtins",
    "copy",
    "base64",
    "hmac",
    "platform",
    "urllib",
    "sqlite3",
    "textwrap",
    "functools",
    "itertools",
    "contextlib",
    "operator",
    # ALM module_01: deterministic byte-shuffle for the non-triviality
    # check in ``ract.antilazy.holdout`` and deterministic sampling in
    # ``ract.antilazy.mutation``. Both use ``random.Random(seed)`` so
    # the perturbation and the per-file cap are reproducible.
    "random",
    # ALM module_01 second-pass fix (finding 1): ``ract.core.predicate``
    # scopes a predicate-id redaction flag via ``contextvars.ContextVar``
    # so held-out predicate ids do not leak into ``predicate.evaluated``
    # trace events. Stdlib.
    "contextvars",
    # security substrate (module_03) — small stdlib deps used by the
    # OS-enforced sandbox backends
    "fnmatch",
    "shlex",
    # module_06: Rootknot.signature deprecation alias emits a
    # ``DeprecationWarning`` via stdlib ``warnings``; provenance.py
    # emits the same at RK-3-skipped-for-v1 sites. Both stdlib.
    "warnings",
    # v0.5 memory-discipline module_02: symbol_index uses stdlib
    # ``types`` for the read-only-mapping proxy.
    "types",
    # v0.5 memory-discipline module_02 (ADR-0032): symbol-index parsers
    # depend on tree-sitter core + per-language grammar packages; the
    # walker uses pathspec for gitignore parity; the watcher uses
    # watchdog observers/events. All four are runtime deps declared in
    # pyproject.toml [project].dependencies (with pinned upper bounds).
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_typescript",
    "tree_sitter_rust",
    "tree_sitter_go",
    "pathspec",
    "watchdog",
}


def test_provenance_doc_exists() -> None:
    assert PROVENANCE_DOC.is_file(), f"Public provenance doc missing: {PROVENANCE_DOC}"


def test_provenance_doc_is_concise() -> None:
    text = PROVENANCE_DOC.read_text(encoding="utf-8")
    word_count = len(text.split())
    assert word_count <= 800, f"PROVENANCE.md is {word_count} words; limit is 800"


@pytest.mark.parametrize(
    "phrase",
    [
        "Rootknot",
        "ed25519",
        "PROVENANCE_FAILURE",
        "independent",
        "verify_workspace",
        "RK-1",
        "RK-2",
        # module_03 (v0.4.1 intent-fidelity Second Pass Q2): the public
        # attestation surface must name the v0.4 extended attestations so
        # readers do not conclude Rootknots stop at the v0.2/v0.3 shape.
        "RK-3",
        "AL-1",
        "environment_signature",
        "antilazy_signature",
    ],
)
def test_provenance_doc_names_real_symbols(phrase: str) -> None:
    text = PROVENANCE_DOC.read_text(encoding="utf-8")
    assert phrase in text, (
        f"PROVENANCE.md must reference '{phrase}' so every claim is grounded "
        "in a real symbol or invariant."
    )


def test_no_forbidden_imports_in_source() -> None:
    """No src/ract module may import from a private/internal/undeclared root.

    The independence claim in PROVENANCE.md is only true if the source does
    not reach into a private package. This scans every ``.py`` file under
    ``src/ract`` via AST (not regex) and fails on any import root not in
    ALLOWED_IMPORT_ROOTS.
    """
    forbidden: list[tuple[Path, str]] = []
    for path in SRC_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            forbidden.append((path, f"<unparseable: {exc}>"))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        forbidden.append((path, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        forbidden.append((path, node.module))
    assert not forbidden, (
        "Forbidden imports found in src/ract (not in ALLOWED_IMPORT_ROOTS); "
        "either add a declared dependency to pyproject.toml and this allowlist, "
        "or remove the import: " + ", ".join(f"{p}:{m}" for p, m in forbidden)
    )


# RACT 0.3.0

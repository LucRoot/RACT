"""Grep-gate: every ``*sandbox*.py`` backend imports build_sandbox_env.

v0.5.1 wiring module_04 (Lens C C-02 closure). The Lens C audit
demanded that every sandbox backend -- Linux bwrap, macOS Seatbelt,
Windows unenforced stub -- apply the ``NEVER_PASSTHROUGH`` deny
surface via ``ract.security.sandbox_env.build_sandbox_env``. Before
the wiring pipeline, only the Windows stub called it; the enforced
backends bypassed it entirely.

This grep-gate refuses regressions: if a new backend file lands
anywhere under ``src/ract/**/*sandbox*.py`` (Windows-native, WSL,
Docker, executor-side wrappers, ...) it must also import
``build_sandbox_env``. The walk is deliberately package-wide rather
than confined to ``src/ract/security/`` so a new backend module
that lands in ``src/ract/executor/`` (or elsewhere) cannot silently
regress the credential-exfil defense (module_04 second-pass Q7).

The primitive module ``sandbox_env.py`` and the dispatch module
``sandbox.py`` are exempt:

- ``sandbox_env.py`` DEFINES ``build_sandbox_env``; it does not
  import itself.
- ``sandbox.py`` is the platform dispatch layer; it calls
  ``build_sandbox_env`` from inside ``UnenforcedSandbox.enter``.
  The import is inside a function body (lazy import to avoid a
  cycle at module load), so the file-level AST scan below finds it.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-02.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_04.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ract"


# Files exempt from the import-check. ``sandbox_env.py`` DEFINES
# ``build_sandbox_env`` and does not import itself. Add more only
# when a file's name matches ``*sandbox*.py`` but it does not act
# as a backend (e.g., a future ``sandbox_env_extras.py`` primitive).
_EXEMPT_FILENAMES: frozenset[str] = frozenset({"sandbox_env.py"})


def _iter_backend_files() -> list[Path]:
    """Return every sandbox backend file anywhere under ``src/ract/``.

    Walks the full package tree (not just ``src/ract/security/``) so a
    backend that lands in a sibling package (e.g. ``src/ract/executor/
    wsl_sandbox.py``) is also gated. Excludes files in
    ``_EXEMPT_FILENAMES`` (the primitive itself).
    """
    files: list[Path] = []
    for path in sorted(_SRC_ROOT.rglob("*sandbox*.py")):
        if path.name in _EXEMPT_FILENAMES:
            continue
        files.append(path)
    return files


def _imports_build_sandbox_env(text: str) -> bool:
    """Return True when the file imports ``build_sandbox_env``.

    Accepts both module-level ``from ract.security.sandbox_env
    import build_sandbox_env`` and function-body lazy imports
    (the Windows stub uses the lazy shape to avoid an import cycle
    with ``ract.trace.sink``).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module != "ract.security.sandbox_env":
                continue
            for alias in node.names:
                if alias.name == "build_sandbox_env":
                    return True
    return False


def test_every_sandbox_backend_imports_build_sandbox_env() -> None:
    """Grep-gate: every backend routes env through NEVER_PASSTHROUGH."""
    files = _iter_backend_files()
    assert files, "no sandbox backend files discovered — path drift?"
    missing: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if not _imports_build_sandbox_env(text):
            missing.append(path.name)
    assert not missing, (
        "wiring module_04 (Lens C C-02): the following sandbox backend "
        "files do NOT import ``build_sandbox_env`` -- credential-exfil "
        "defense is bypassed on those backends. Files: "
        f"{missing}. Fix: import ``build_sandbox_env`` from "
        "``ract.security.sandbox_env`` and route "
        "``manifest.env.passthrough`` through it before emitting any "
        "child-env args."
    )


def test_walk_root_is_package_wide_not_just_security_dir() -> None:
    """SP Q7 amendment: walk covers ``src/ract/**``, not just security/.

    Locks the Q7 amendment (broader discovery). A future backend that
    lands at ``src/ract/executor/wsl_sandbox.py`` (or any other
    subpackage) must ALSO be discovered by ``_iter_backend_files``.
    This test asserts the walk root is the package root, not the
    security sub-directory, so a future path drift trips loud.
    """
    assert _SRC_ROOT.name == "ract", (
        "SP Q7 amendment: sandbox-backend discovery must walk the "
        "full ``src/ract/`` tree so a backend in a sibling package "
        f"(e.g. src/ract/executor/wsl_sandbox.py) is gated; got {_SRC_ROOT}"
    )
    # Verify the current known backends are all discovered.
    discovered_names = {p.name for p in _iter_backend_files()}
    for expected in ("sandbox.py", "sandbox_linux.py", "sandbox_macos.py"):
        assert expected in discovered_names, (
            f"expected backend {expected} not discovered by walk "
            f"(got {sorted(discovered_names)})"
        )


def test_sandbox_env_scrubbed_in_event_kind_literal() -> None:
    """Grep-gate: ``sandbox.env_scrubbed`` is in the closed EventKind.

    An emit that references an EventKind not in the Literal fails the
    write-time gate at ``Event.__post_init__``. This test asserts the
    string is registered so the runtime emits from Linux + macOS +
    Windows backends never raise.
    """
    from ract.trace.events import LEGAL_EVENT_KINDS

    assert "sandbox.env_scrubbed" in LEGAL_EVENT_KINDS, (
        "wiring module_04: sandbox.env_scrubbed must be in the closed "
        "EventKind vocabulary; producers in the sandbox backends emit "
        "it on every enter()."
    )


# RACT 0.5.1

"""Grep-gate: every production ``subprocess.run`` / ``subprocess.Popen``
in ``src/ract/`` must either route through the substrate
tool-invocation gate or appear in the exempt-site registry.

v0.5.1 wiring module_03 (Lens C C-01) closure. The Lens C audit
demanded every production tool invocation route through
:meth:`SubstrateLoop.invoke_tool`. Some subprocess spawns are
SUBSTRATE INFRASTRUCTURE (git ops the substrate itself performs),
some are OBSERVABILITY INFRASTRUCTURE (whisperer/fence/memory git
log), and some are the wire layer under a higher-level gate. The
exempt-site registry at
:data:`ract.executor.tool_gate._EXEMPT_SITES` names each such site
with an explicit reason string. The migrated site (the Executor
MCP tool_call path) routes through the gate directly.

This test scans every ``.py`` file under ``src/ract/`` for a
``subprocess.run(`` / ``subprocess.Popen(`` / ``subprocess.call(``
/ ``subprocess.check_output(`` / ``subprocess.check_call(``
invocation, and asserts each containing file either:

- appears in :data:`_EXEMPT_SITES` (with a reason), OR
- is the tool_gate primitive itself (definition-site allowance).

A new subprocess caller that lands without either shape trips
this test.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-01.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_03.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ract.executor.tool_gate import exempt_sites


# The tool_gate module names ``subprocess.Popen`` in a docstring
# and a type annotation for its process_group primitive; the
# grep-gate must allow the tool_gate file itself. Additionally,
# tests / dev-tooling under src/ are absent (tests live under
# ``tests/``).
_GATE_DEFINITION_FILES: frozenset[str] = frozenset(
    {
        # These files use subprocess as the SPAWN GATE PRIMITIVE
        # (module_05); they are the mechanism, not a caller.
        # Already listed in exempt_sites but named here so the test
        # is legible.
    }
)


_SUBPROCESS_ATTRS: frozenset[str] = frozenset(
    {"run", "Popen", "call", "check_output", "check_call"}
)


def _iter_py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel:
            continue
        yield rel, path


def _find_subprocess_calls(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, api)`` for every real ``subprocess.<api>(...)``
    call node in ``text``. Uses AST so mentions inside docstrings and
    comments are ignored.
    """
    hits: list[tuple[int, str]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return hits
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # ``subprocess.<api>(...)``
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in _SUBPROCESS_ATTRS
        ):
            hits.append((getattr(node, "lineno", 0), func.attr))
    return hits


def test_no_ungated_subprocess_in_src() -> None:
    """No production file may call ``subprocess.run/Popen/call/...``
    unless it appears in the exempt-site registry (or is the tool_gate
    primitive itself)."""
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    assert src_root.is_dir(), src_root

    exempt = exempt_sites()

    offenders: list[tuple[str, int, str]] = []
    for rel, path in _iter_py_files(src_root):
        # Skip the exempt list (each entry carries a documented reason).
        if rel in exempt:
            continue
        if rel in _GATE_DEFINITION_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, api in _find_subprocess_calls(text):
            offenders.append((rel, lineno, f"subprocess.{api}(...)"))

    assert not offenders, (
        "Ungated subprocess call detected in src/ract/ (Lens C C-01 "
        "regression). Route through SubstrateLoop.invoke_tool or add "
        "an explicit exempt_sites entry in ract.executor.tool_gate "
        "with a reason string.\n"
        + "\n".join(f"  {rel}:{ln}: {src}" for rel, ln, src in offenders)
    )


def test_exempt_sites_actually_exist() -> None:
    """Every exempt-site path must correspond to a real file under src/ract/."""
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    assert src_root.is_dir(), src_root
    exempt = exempt_sites()
    missing: list[str] = []
    for rel in exempt:
        candidate = src_root / rel
        if not candidate.is_file():
            missing.append(rel)
    assert not missing, (
        f"exempt_sites references files that do not exist under src/ract/: "
        f"{missing!r}. Update _EXEMPT_SITES."
    )


def test_exempt_sites_have_reason_strings() -> None:
    """Every exempt entry MUST carry a non-empty reason string.

    The reason is load-bearing for the audit posture: an operator
    reviewing the gate registry can reconstruct why a site is
    permitted to bypass the four-gate check without spelunking
    through git history.
    """
    exempt = exempt_sites()
    blank: list[str] = []
    for rel, reason in exempt.items():
        if not reason or not reason.strip():
            blank.append(rel)
    assert not blank, (
        f"exempt_sites entries with empty reason string: {blank!r}. "
        "Every exemption requires an explicit reason for the "
        "audit trail."
    )


def test_executor_mcp_tool_call_routes_through_gate() -> None:
    """The migrated site (Executor MCP tool_call) must reference
    ``substrate_loop.invoke_tool``. A regression that reverts the
    module_03 migration would delete the ``invoke_tool`` reference
    from executor/steps.py.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    steps_path = src_root / "executor" / "steps.py"
    assert steps_path.is_file(), steps_path
    text = steps_path.read_text(encoding="utf-8")
    assert "substrate_loop.invoke_tool" in text, (
        "executor/steps.py must route MCP tool_call through "
        "substrate_loop.invoke_tool (Lens C C-01 wire-in). If the "
        "migration is being intentionally reverted, update this "
        "test alongside."
    )
    # And the tool_id prefix must be ``mcp:`` so the gate's manifest
    # allowlist can distinguish MCP tools from other capability
    # families (v0.6 will add polyglot AST tools, subprocess tools,
    # etc. under distinct prefixes).
    assert 'f"mcp:{tool_name}"' in text or "'mcp:'" in text, (
        "executor/steps.py must qualify MCP tool ids as "
        "``mcp:<qualified_name>`` for the manifest allowlist family."
    )

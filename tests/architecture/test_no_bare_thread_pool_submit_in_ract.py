"""Grep-gate: no bare ``ThreadPoolExecutor.submit`` /
``pool.submit`` / ``asyncio.gather`` inside ``src/ract/`` outside an
allowlist.

v0.5.1 wiring module_06 (Lens G G-01 + Lens H C4) closure. The
Lens G finding established that :meth:`LoopController._run_with_timeout`
submitted ``run_ract`` to a bare :class:`ThreadPoolExecutor`, dropping
the ambient run_id ``LoopController.run`` had bound via
:func:`ract.runtime.bind_run_id`. The fix wraps the submit with
:func:`ract.runtime.run_with_ambient`. This test locks the wire-in in
place -- any future ``.submit(callable, ...)`` or
``executor.submit(fn, ...)`` at a bare call site (i.e. NOT
``executor.submit(run_with_ambient(fn, ...))``) triggers a failure.

The allowlist below records sites explicitly reviewed as safe
non-propagation (e.g., a purely synchronous test-harness spawn that
runs in a scope where ambient is guaranteed empty).

Reference:
- ``_BUILD/audit_2026-08-21/lens_G_loop_controller.md`` G-01.
- Lens H C4 (ThreadPoolExecutor audit item, per master spec).
- ``_BUILD/ract_v0.5.1_wiring_completion/module_06.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import ract


_SRC_ROOT = Path(ract.__file__).parent


# Files where a bare submit is explicitly allowed. Every entry MUST
# carry a per-line reason recorded in ``module_06.md`` under "sweep
# audit". Empty by default -- the two production submit sites
# (loop_controller._run_with_timeout, cli.py scan-timeout) are both
# wrapped in ``run_with_ambient``.
_EXEMPT: frozenset[tuple[str, str]] = frozenset()


def _is_bare_submit(call: ast.Call) -> bool:
    """Return True when the call is ``<something>.submit(<callable>, ...)``
    and the first positional arg is NOT ``run_with_ambient(...)``.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "submit":
        return False
    if not call.args:
        # ``submit()`` with only kwargs -- weird but not our concern.
        return False
    first = call.args[0]
    # Wrapped call: ``executor.submit(run_with_ambient(fn, ...))``.
    if (
        isinstance(first, ast.Call)
        and isinstance(first.func, ast.Name)
        and first.func.id == "run_with_ambient"
    ):
        return False
    # ``executor.submit(some_name_or_attribute, ...)`` -- BARE.
    return True


def _is_asyncio_gather(call: ast.Call) -> bool:
    """Return True when the call is ``asyncio.gather(...)`` -- catches
    bare gather sites even inside ``providers/``, ``retrieval/``,
    ``memory/`` (SP Q4 amendment: widen the concurrency sweep).
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "gather":
        return False
    if not isinstance(func.value, ast.Name):
        return False
    return func.value.id == "asyncio"


def _is_run_in_executor(call: ast.Call) -> bool:
    """Return True when the call is ``<loop>.run_in_executor(<pool>, fn, ...)``
    and ``fn`` (positional arg index 1) is NOT wrapped in
    :func:`ract.runtime.run_with_ambient`.

    SP Q4 amendment: ``loop.run_in_executor(pool, fn, arg1, arg2)``
    also drops the ambient ContextVar unless the caller opts in via
    the wrap. ``asyncio.to_thread`` inherits the current context in
    Python 3.11+ (documented in :mod:`ract.runtime`); we do not flag
    that pattern.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "run_in_executor":
        return False
    # Two args expected: pool (may be None), callable. The callable is
    # positional arg index 1.
    if len(call.args) < 2:
        return False
    callable_arg = call.args[1]
    if (
        isinstance(callable_arg, ast.Call)
        and isinstance(callable_arg.func, ast.Name)
        and callable_arg.func.id == "run_with_ambient"
    ):
        return False
    return True


def _is_process_pool_submit(call: ast.Call) -> bool:
    """Return True when the call is a ProcessPoolExecutor instantiation
    followed by a .submit inside the same expression -- guarded by the
    same ambient-wrap contract.

    Complementary coverage for :class:`concurrent.futures.ProcessPoolExecutor`:
    ContextVar values do not cross the process boundary AT ALL, so
    process-pool sites MUST document their own explicit run_id
    propagation. This detector fires on any ``ProcessPoolExecutor``
    reference inside ``src/ract/`` so an unwrapped process-pool spawn
    (which no production site currently uses) can never slip in.
    """
    func = call.func
    if isinstance(func, ast.Name) and func.id == "ProcessPoolExecutor":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "ProcessPoolExecutor":
        return True
    return False


def _scan_file(path: Path) -> list[tuple[Path, int, str]]:
    """Return ``(path, lineno, snippet)`` for every offending call in ``path``."""
    if (str(path), str(path.name)) in _EXEMPT:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    findings: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_bare_submit(node):
            findings.append((path, node.lineno, "bare .submit(callable)"))
        elif _is_asyncio_gather(node):
            findings.append((path, node.lineno, "asyncio.gather (may drop ContextVar)"))
        elif _is_run_in_executor(node):
            findings.append(
                (
                    path,
                    node.lineno,
                    "loop.run_in_executor without run_with_ambient wrap",
                )
            )
        elif _is_process_pool_submit(node):
            findings.append(
                (
                    path,
                    node.lineno,
                    "ProcessPoolExecutor (ContextVar cannot cross processes)",
                )
            )
    return findings


def test_no_bare_thread_pool_submit_in_src_ract() -> None:
    """Every ``.submit(callable, ...)`` inside ``src/ract/`` must wrap the
    callable with :func:`ract.runtime.run_with_ambient`.
    """
    offenders: list[str] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT)
        # The ambient-propagation helper's docstring shows the WRONG
        # pattern as an example under ``ThreadPoolExecutor``; skip.
        if rel.as_posix() == "runtime.py":
            continue
        for path, lineno, reason in _scan_file(py_file):
            offenders.append(f"{path.relative_to(_SRC_ROOT)}:{lineno} {reason}")
    assert not offenders, (
        "Bare ThreadPoolExecutor.submit / asyncio.gather sites found in "
        "src/ract/. Wrap each callable with ract.runtime.run_with_ambient "
        "so the ambient run_id propagates into the worker context "
        "(Lens G G-01 / Lens H C4).\n" + "\n".join(offenders)
    )


def test_loop_controller_run_with_timeout_uses_ambient_wrap() -> None:
    """Structural lock: ``LoopController._run_with_timeout`` MUST invoke
    ``executor.submit(run_with_ambient(run_ract, ...))`` -- a bare
    ``executor.submit(run_ract, ...)`` fails Lens G G-01.
    """
    from ract import loop_controller as lc_mod

    src = Path(lc_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_run_with_timeout"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "submit"
            ):
                if not sub.args:
                    continue
                first = sub.args[0]
                assert isinstance(first, ast.Call), (
                    "_run_with_timeout: executor.submit's first arg must be a "
                    "run_with_ambient(...) call, not a bare reference."
                )
                assert (
                    isinstance(first.func, ast.Name)
                    and first.func.id == "run_with_ambient"
                ), (
                    "_run_with_timeout: executor.submit's first arg must be "
                    "run_with_ambient(...), got %r" % ast.dump(first.func)
                )
                found = True
    assert found, "No executor.submit(...) call found in _run_with_timeout"

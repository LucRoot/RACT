"""LSP-integration tests for module_03.

Two variants:

- Unit-level tests that verify :func:`~ract.memory.lsp.probe_lsp`
  short-circuits cleanly on unsupported languages and rejects an
  unknown language label.
- Live-integration tests skipped when the language binary is not
  on PATH. When ``jedi-language-server`` (or another Python LSP)
  is installed, the live path exercises the multilspy wrapper end
  to end.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from ract.memory.lsp import (
    LSP_ADAPTERS,
    LSP_BINARY_HINTS,
    LspUnavailableError,
    available_languages,
    probe_lsp,
)


def test_probe_lsp_rejects_unknown_language():
    r = probe_lsp("cobol")
    assert r.available is False
    assert r.error_message is not None
    assert "cobol" in r.error_message.lower() or "not in" in r.error_message


def test_lsp_adapters_matches_module_02_languages():
    """module_02 POST-A constraint: the LSP language set matches
    the languages module_02 parses. Adding a language here without
    a parser would populate the graph with symbol ids that do not
    exist."""
    assert set(LSP_ADAPTERS) == {"python", "typescript", "rust", "go"}


def test_lsp_binary_hints_cover_every_adapter():
    for lang in LSP_ADAPTERS:
        assert lang in LSP_BINARY_HINTS
        assert LSP_BINARY_HINTS[lang]


def test_available_languages_returns_probe_per_language(tmp_path: Path, monkeypatch):
    # B-134 (WRIGHT's FOUND): this test started a real python language server
    # where multilspy is installed, and it never answered. The probe's own
    # behaviour is tested below; here no server is started.
    # G-240: the probe runs in a child process; the stub child starts nothing.
    _stub(monkeypatch, _ANSWERS)
    results = available_languages(("python", "cobol"), tmp_path)
    assert set(results) == {"python", "cobol"}
    assert results["cobol"].available is False
    assert results["python"].available is False


def test_a_probe_that_never_answers_is_bounded(tmp_path: Path, monkeypatch):
    """B-134: a language server that never answers does not hold the caller."""
    import ract.memory.lsp as lsp

    pids = tmp_path / "pids"
    pids.mkdir()
    _stub(monkeypatch, _HANGS, pids)
    result = lsp.bounded_probe("python", tmp_path, budget_s=3)
    assert result.available is False and "did not answer in" in result.error_message


def test_lsp_client_rejects_unsupported_language(tmp_path: Path):
    from ract.memory.lsp import LspClient

    with pytest.raises(LspUnavailableError):
        LspClient(tmp_path, "cobol")


def test_probe_lsp_uses_dedicated_probe_fixture_per_language():
    """Second Pass Q3 regression: probe_lsp writes a real fixture
    file and calls request_references directly (not through
    references_of, which would silently swallow a
    capability-not-supported error).
    """
    from ract.memory.lsp import _PROBE_FILE

    assert set(_PROBE_FILE) == {"python", "typescript", "rust", "go"}
    for name, content in _PROBE_FILE.values():
        assert name.startswith("___ract_lsp_probe___")
        assert content.strip()


@pytest.mark.skipif(
    importlib.util.find_spec("multilspy") is None
    or (
        shutil.which("jedi-language-server") is None
        and shutil.which("pylsp") is None
        and shutil.which("pyright-langserver") is None
    ),
    reason="multilspy or a Python LSP binary is missing; the live probe is skipped (B-068)",
)
def test_probe_lsp_python_live(tmp_path: Path):
    # Give the probe a real repo root with a real file so multilspy
    # does not choke on the directory-as-file read path.
    (tmp_path / "x.py").write_text("def x(): pass\n", encoding="utf-8")
    r = probe_lsp("python", tmp_path)
    assert r.available is True
    assert r.latency_ms > 0


# RACT 0.5.0


def test_probe_reports_a_missing_multilspy_in_plain_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B-068: no install. The package's absence is simulated where the import happens.
    from ract.memory import lsp

    def missing() -> None:
        raise ModuleNotFoundError("No module named 'multilspy'")

    monkeypatch.setattr(lsp, "_load_multilspy", missing)
    (tmp_path / "x.py").write_text("def x(): pass" + chr(10), encoding="utf-8")
    r = lsp.probe_lsp("python", tmp_path)
    assert r.available is False
    assert "multilspy" in (r.error_message or "")
    assert "Traceback" not in (r.error_message or "")


# --- G-240: the probe is a child process group; past the budget its tree ends ---

_ANSWERS = (
    "import dataclasses, json, sys\n"
    "from ract.memory.lsp import LspProbeResult\n"
    "r = LspProbeResult(language=sys.argv[1], available=False, error_message='stub')\n"
    "print('RACT-PROBE ' + json.dumps(dataclasses.asdict(r)), flush=True)\n"
)

# A "server" that never answers: it starts a grandchild, writes its pid, waits.
_HANGS = (
    "import subprocess, sys, time\n"
    "server = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(sys.argv[3], 'w').write(str(server.pid))\n"
    "time.sleep(120)\n"
)


def _stub(monkeypatch, script: str, pid_dir: Path | None = None) -> None:
    import sys

    import ract.memory.lsp as lsp

    def argv(language: str, repo_root: str) -> list[str]:
        extra = [str(pid_dir / f"{language}.pid")] if pid_dir is not None else []
        return [sys.executable, "-c", script, language, repo_root, *extra]

    monkeypatch.setattr(lsp, "_child_argv", argv)


def _alive(pid: int) -> bool:
    import os
    import subprocess

    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_the_child_result_is_read_back(tmp_path: Path, monkeypatch) -> None:
    import ract.memory.lsp as lsp

    _stub(monkeypatch, _ANSWERS)
    results = lsp.bounded_probes(("python", "rust"), tmp_path, budget_s=30)
    assert set(results) == {"python", "rust"}
    assert all(not r.available and r.error_message == "stub" for r in results.values())


def test_the_probes_share_one_budget_and_leave_no_server(
    tmp_path: Path, monkeypatch
) -> None:
    """B-136 and G-240: four probes that never answer take one budget, and
    after it no probe or server they started is left running."""
    import time

    import ract.memory.lsp as lsp

    pids = tmp_path / "pids"
    pids.mkdir()
    _stub(monkeypatch, _HANGS, pids)
    langs = ("python", "typescript", "rust", "go")
    started = time.monotonic()
    results = lsp.bounded_probes(langs, tmp_path, budget_s=4)
    elapsed = time.monotonic() - started
    assert elapsed < 15
    assert all(
        not r.available and "did not answer" in r.error_message
        for r in results.values()
    )
    servers = [int((pids / f"{lang}.pid").read_text()) for lang in langs]
    deadline = time.monotonic() + 10
    while any(_alive(pid) for pid in servers) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not any(_alive(pid) for pid in servers), servers

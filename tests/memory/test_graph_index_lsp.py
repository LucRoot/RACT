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
    import ract.memory.lsp as lsp

    def no_server(*_a, **_kw):
        raise ModuleNotFoundError("multilspy is not used in this test")

    monkeypatch.setattr(lsp, "LspClient", no_server)
    results = available_languages(("python", "cobol"), tmp_path)
    assert set(results) == {"python", "cobol"}
    assert results["cobol"].available is False
    assert results["python"].available is False


def test_a_probe_that_never_answers_is_bounded(tmp_path: Path, monkeypatch):
    """B-134: a language server that never answers does not hold the caller."""
    import threading

    import ract.memory.lsp as lsp

    stop = threading.Event()

    def hangs(language, repo_root=None):
        stop.wait(30)
        raise AssertionError("not reached in the budget")

    monkeypatch.setattr(lsp, "probe_lsp", hangs)
    result = lsp.bounded_probe("python", tmp_path, budget_s=0.2)
    stop.set()
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

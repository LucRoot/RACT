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


def test_available_languages_returns_probe_per_language(tmp_path: Path):
    results = available_languages(("python", "cobol"), tmp_path)
    assert set(results) == {"python", "cobol"}
    assert results["cobol"].available is False


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
    shutil.which("jedi-language-server") is None
    and shutil.which("pylsp") is None
    and shutil.which("pyright-langserver") is None,
    reason="No Python LSP binary on PATH; live probe skipped",
)
def test_probe_lsp_python_live(tmp_path: Path):
    # Give the probe a real repo root with a real file so multilspy
    # does not choke on the directory-as-file read path.
    (tmp_path / "x.py").write_text("def x(): pass\n", encoding="utf-8")
    r = probe_lsp("python", tmp_path)
    assert r.available is True
    assert r.latency_ms > 0


# RACT 0.5.0

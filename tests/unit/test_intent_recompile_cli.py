"""``ract intent recompile`` CLI verb tests (v0.5.1 module_04)."""

from __future__ import annotations

import io
import json
import secrets
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from ract.cli import main as cli_main
from ract.core.intent_recompile import (
    OPERATOR_KEY_ENV,
    OperatorKeyMissingError,
    _load_operator_key,
    recompile_intent,
)
from ract.core.suite_chain import SuiteChain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_tree(tmp_path: Path) -> dict[str, Path]:
    """Build a minimal .ract/runs/<id>/ tree with a suite.json + operator.key."""
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    runs_root = ract_dir / "runs"
    runs_root.mkdir()
    run_dir = runs_root / "run-fixture-001"
    run_dir.mkdir()

    # Seed suite.json with an initial compile so the recompile path can
    # load a predecessor. Use IntentCompiler with an empty workspace
    # -- module_04 recompile takes the same path.
    from ract.core.compile import IntentCompiler
    from ract.core.loop import WorkspaceSnapshot

    compiler = IntentCompiler()
    initial = compiler.compile("initial intent v1", WorkspaceSnapshot())
    suite = initial.visible if hasattr(initial, "visible") else initial  # type: ignore[union-attr]
    (run_dir / "suite.json").write_text(suite.to_json(), encoding="utf-8")

    # Operator key marker
    (ract_dir / "operator.key").write_bytes(secrets.token_bytes(64))

    return {"tmp": tmp_path, "ract_dir": ract_dir, "run_dir": run_dir}


# ---------------------------------------------------------------------------
# Operator key discovery
# ---------------------------------------------------------------------------


def test_load_operator_key_from_marker_file(run_tree: dict[str, Path]) -> None:
    key = _load_operator_key(run_tree["ract_dir"])
    assert len(key) >= 32


def test_load_operator_key_from_env_var(tmp_path: Path, monkeypatch) -> None:
    empty_dir = tmp_path / ".ract-empty"
    empty_dir.mkdir()
    hex_key = secrets.token_hex(32)
    monkeypatch.setenv(OPERATOR_KEY_ENV, hex_key)
    key = _load_operator_key(empty_dir)
    assert key == bytes.fromhex(hex_key)


def test_load_operator_key_missing_raises(tmp_path: Path, monkeypatch) -> None:
    empty_dir = tmp_path / ".ract-empty"
    empty_dir.mkdir()
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    with pytest.raises(OperatorKeyMissingError):
        _load_operator_key(empty_dir)


def test_load_operator_key_short_file_raises(tmp_path: Path, monkeypatch) -> None:
    empty_dir = tmp_path / ".ract-short"
    empty_dir.mkdir()
    (empty_dir / "operator.key").write_bytes(b"too-short")
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    with pytest.raises(OperatorKeyMissingError):
        _load_operator_key(empty_dir)


# ---------------------------------------------------------------------------
# Programmatic recompile_intent
# ---------------------------------------------------------------------------


def test_recompile_intent_appends_to_chain(run_tree: dict[str, Path]) -> None:
    run_dir = run_tree["run_dir"]
    result = recompile_intent(
        run_dir=run_dir,
        intent_text="a wholly new intent for v2",
        ract_dir=run_tree["ract_dir"],
    )
    chain = SuiteChain(run_dir)
    entries = chain.entries()
    # Initial entry auto-recorded + operator recompile entry.
    assert len(entries) == 2
    assert entries[0].origin == "initial"
    assert entries[1].origin == "operator_recompile"
    assert entries[1].prompt_digest == result.entry.prompt_digest
    assert entries[1].rootknot_signature is not None


def test_recompile_intent_preserves_chain_history_across_calls(
    run_tree: dict[str, Path],
) -> None:
    run_dir = run_tree["run_dir"]
    recompile_intent(
        run_dir=run_dir,
        intent_text="v2 intent",
        ract_dir=run_tree["ract_dir"],
    )
    recompile_intent(
        run_dir=run_dir,
        intent_text="v3 intent -- further refinement",
        ract_dir=run_tree["ract_dir"],
    )
    chain = SuiteChain(run_dir)
    entries = chain.entries()
    # initial + v2 + v3
    assert len(entries) == 3
    assert entries[0].origin == "initial"
    assert entries[1].origin == "operator_recompile"
    assert entries[2].origin == "operator_recompile"
    # Distinct digests
    digests = [e.prompt_digest for e in entries]
    assert len(set(digests)) == 3


def test_recompile_refuses_without_operator_key(
    tmp_path: Path, monkeypatch, run_tree: dict[str, Path]
) -> None:
    # Point ract_dir at an empty dir + clear env => refusal.
    empty_dir = tmp_path / ".ract-none"
    empty_dir.mkdir()
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    with pytest.raises(OperatorKeyMissingError):
        recompile_intent(
            run_dir=run_tree["run_dir"],
            intent_text="doesn't matter",
            ract_dir=empty_dir,
        )


def test_recompile_refuses_empty_intent(run_tree: dict[str, Path]) -> None:
    from ract.core.intent_recompile import IntentRecompileError

    with pytest.raises(IntentRecompileError):
        recompile_intent(
            run_dir=run_tree["run_dir"],
            intent_text="   ",
            ract_dir=run_tree["ract_dir"],
        )


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


def test_cli_intent_verb_exists() -> None:
    """`ract intent -h` must exit cleanly (verb is wired)."""
    stderr = io.StringIO()
    stdout = io.StringIO()
    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
        pytest.raises(SystemExit) as exc,
    ):
        cli_main(["intent", "-h"])
    assert exc.value.code == 0


def test_cli_intent_recompile_success(run_tree: dict[str, Path]) -> None:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = cli_main(
            [
                "intent",
                "recompile",
                str(run_tree["run_dir"]),
                "--intent-text",
                "v2 intent via CLI",
                "--ract-dir",
                str(run_tree["ract_dir"]),
            ]
        )
    assert rc == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["status"] == "ok"
    assert payload["origin"] == "operator_recompile"
    assert len(payload["prompt_digest"]) == 64  # SHA-256 hex


def test_cli_intent_recompile_no_operator_key_refuses(
    tmp_path: Path, monkeypatch
) -> None:
    # Build a run dir with a suite but NO operator.key anywhere.
    ract_dir = tmp_path / ".ract-orphan"
    ract_dir.mkdir()
    run_dir = tmp_path / "run-orphan"
    run_dir.mkdir()
    from ract.core.compile import IntentCompiler
    from ract.core.loop import WorkspaceSnapshot

    compiler = IntentCompiler()
    initial = compiler.compile("orphan initial", WorkspaceSnapshot())
    suite = initial.visible if hasattr(initial, "visible") else initial  # type: ignore[union-attr]
    (run_dir / "suite.json").write_text(suite.to_json(), encoding="utf-8")

    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = cli_main(
            [
                "intent",
                "recompile",
                str(run_dir),
                "--intent-text",
                "attacker try",
                "--ract-dir",
                str(ract_dir),
            ]
        )
    assert rc == 3  # OperatorKeyMissingError -> exit code 3
    assert "operator key" in stderr.getvalue().lower()


def test_sp_q4a_ract_dir_resolves_to_realpath(tmp_path: Path, monkeypatch) -> None:
    """SP Q4a amendment: caller-supplied ract_dir goes through
    Path.resolve(strict=False) so a relative path or symlink race
    cannot redirect the loader to a decoy operator.key.
    """
    real_dir = tmp_path / "real-ract"
    real_dir.mkdir()
    (real_dir / "operator.key").write_bytes(secrets.token_bytes(64))

    # Pass a NON-normalised relative-style path (with ".." mid-path).
    weird_path = tmp_path / "real-ract" / ".." / "real-ract"
    # Should still resolve to real_dir and load the key.
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    key = _load_operator_key(weird_path)
    assert len(key) >= 32


def test_sp_q6b_exit_code_4_missing_suite(tmp_path: Path, monkeypatch) -> None:
    """SP Q6b: missing suite.json => exit code 4 (was 2)."""
    ract_dir = tmp_path / ".ract-for-4"
    ract_dir.mkdir()
    (ract_dir / "operator.key").write_bytes(secrets.token_bytes(64))
    run_dir = tmp_path / "run-no-suite"
    run_dir.mkdir()  # empty -- no suite.json

    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = cli_main(
            [
                "intent",
                "recompile",
                str(run_dir),
                "--intent-text",
                "x",
                "--ract-dir",
                str(ract_dir),
            ]
        )
    assert rc == 4


def test_cli_intent_recompile_intent_file_source(
    run_tree: dict[str, Path], tmp_path: Path
) -> None:
    intent_file = tmp_path / "new_intent.txt"
    intent_file.write_text("v2 intent from file source", encoding="utf-8")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = cli_main(
            [
                "intent",
                "recompile",
                str(run_tree["run_dir"]),
                "--intent-file",
                str(intent_file),
                "--ract-dir",
                str(run_tree["ract_dir"]),
            ]
        )
    assert rc == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["status"] == "ok"

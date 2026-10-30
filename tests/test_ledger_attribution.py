"""V7-08: ledger records carry run, step and role; /cost --by groups by them.

Ids only, never content: a record gains exactly three keys. A record written
before them still reads (it groups as "(none)").
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from ract import egress_ledger
from ract.session_turn import run_turn
from tests.test_repl import _session
from tests.test_session_turn import _collect, _repo, _request

KEYS_BEFORE = {
    "t",
    "pid",
    "purpose",
    "kind",
    "host",
    "port",
    "bytes_out",
    "status",
    "ms",
    "bytes_in",
    "tokens_in",
    "tokens_out",
}


def test_ledger_records_run_step_and_role(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "egress.jsonl"
    monkeypatch.setenv("RACT_EGRESS_LEDGER", str(ledger))
    server = fake_model_server("plan_three_steps")
    ws = _repo(tmp_path, server.base_url)
    stream, _events = _collect()
    code = run_turn(stream, _request(ws), turn=1, cancel=threading.Event())
    assert code == 0
    model = [r for r in egress_ledger.read(ledger) if r["kind"] == "model"]
    assert len(model) == 4  # the plan, then one request per step
    for record in model:
        assert set(record) == KEYS_BEFORE | {"run", "step", "role"}, record
        assert record["run"] == f"{stream.session}:1"
    plan, *steps = model
    assert (plan["role"], plan["step"]) == ("manager", "")
    assert [(r["role"], r["step"]) for r in steps] == [
        ("executor", "1"),
        ("executor", "2"),
        ("executor", "3"),
    ]


def test_purpose_blocks_nest_and_restore() -> None:
    with egress_ledger.purpose("step 2", step=2, role="executor"):
        with egress_ledger.purpose("role:reviewer", role="reviewer"):
            assert egress_ledger._attribution()["step"] == "2"  # inherited
            assert egress_ledger._attribution()["role"] == "reviewer"
        assert egress_ledger._attribution()["role"] == "executor"
    assert egress_ledger._attribution() == {"run": "", "step": "", "role": ""}


# --- /cost --by -------------------------------------------------------------


def _ledger_with_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "egress.jsonl"
    monkeypatch.setenv("RACT_EGRESS_LEDGER", str(ledger))
    base = {
        "t": "2999-01-01T00:00:00.000+00:00",
        "pid": os.getpid(),
        "kind": "model",
        "host": "127.0.0.1",
        "port": 8080,
        "bytes_out": 100,
        "status": 200,
        "ms": 10,
        "bytes_in": 50,
        "tokens_in": 10,
        "tokens_out": 2,
    }
    rows = [
        {**base, "purpose": "plan", "run": "s-1:1", "step": "", "role": "manager"},
        {**base, "purpose": "step 1", "run": "s-1:1", "step": "1", "role": "executor"},
        {**base, "purpose": "step 2", "run": "s-1:1", "step": "2", "role": "executor"},
        {
            **base,
            "purpose": "role:reviewer",
            "run": "s-1:1",
            "step": "2",
            "role": "reviewer",
        },
        {**base, "purpose": "plan"},  # written before V7-08: no run, step or role
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: str, cols: int) -> str:
    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((cols, 24))
    )
    session, _, console = _session(config=tmp_path / "ract.yaml")
    session.state.started_at = "2000-01-01T00:00:00.000+00:00"
    session.handle(f"/cost {args}".strip())
    return console.text


@pytest.mark.parametrize("cols", [60, 40])
def test_cost_by_step_and_role_fits_the_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cols: int
) -> None:
    _ledger_with_records(tmp_path, monkeypatch)
    by_step = _cost(tmp_path, monkeypatch, "--by step", cols)
    assert "model requests by step:" in by_step
    shown = [line.strip() for line in by_step.splitlines()]
    assert any(x.startswith("1: 1 request") for x in shown)
    assert any(x.startswith("2: 2 requests") for x in shown)
    assert "(none): 2 requests" in by_step  # the plan and the old record
    by_role = _cost(tmp_path, monkeypatch, "--by=role", cols)
    assert "model requests by role:" in by_role
    assert "executor: 2 requests" in by_role and "reviewer: 1 request" in by_role
    for text in (by_step, by_role):
        for line in text.splitlines():
            assert len(line) <= cols, line


def test_cost_without_by_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger_with_records(tmp_path, monkeypatch)
    text = _cost(tmp_path, monkeypatch, "", 80)
    assert "model requests by purpose:" in text and "plan: 2 requests" in text


def test_cost_with_an_unknown_grouping_says_how(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger_with_records(tmp_path, monkeypatch)
    assert "usage: /cost [--by purpose|step|role]" in _cost(
        tmp_path, monkeypatch, "--by host", 80
    )


def test_an_old_record_still_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger_with_records(tmp_path, monkeypatch)
    records = egress_ledger.read(tmp_path / "egress.jsonl")
    assert len(records) == 5
    lines = egress_ledger.describe(records, by="role")
    assert any(line.startswith("  (none): 1 request") for line in lines), lines

"""Tests for the ract operator-queue --json CLI output."""

from __future__ import annotations


import json
import os
import subprocess
import sys


def test_cli_operator_queue_list_json_reports_pending_request(tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    env = {**os.environ, "RACT_HANDSHAKE_QUEUE": str(queue_path)}

    raise_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "operator-queue",
            "raise",
            "--question",
            "What is the meaning of RACT?",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert raise_result.returncode == 0, raise_result.stderr

    list_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "operator-queue",
            "list",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert list_result.returncode == 0, list_result.stderr
    pending = json.loads(list_result.stdout)
    assert isinstance(pending, list)
    assert any("meaning of RACT" in item.get("question", "") for item in pending)


def test_cli_operator_queue_answer_json_reports_recorded_answer(tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    env = {**os.environ, "RACT_HANDSHAKE_QUEUE": str(queue_path)}

    raise_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "operator-queue",
            "raise",
            "--question",
            "Should we refactor?",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert raise_result.returncode == 0, raise_result.stderr
    request_id = raise_result.stdout.split(":")[-1].strip()

    answer_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "operator-queue",
            "answer",
            "--id",
            request_id,
            "--response",
            "Yes, after the tests pass.",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert answer_result.returncode == 0, answer_result.stderr
    data = json.loads(answer_result.stdout)
    assert data["recorded"] is True
    assert data["id"] == request_id


# RACT 0.1.2 - Trust and tooling

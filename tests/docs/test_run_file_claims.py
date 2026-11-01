"""B-223 (D-166): the documents say what a run really creates.

The ground truth (measured on this tip, 2026-11-01, a headless
``ract -p --accept-edits`` turn against the fake server in a temporary
project, the user state directory isolated):

- in the project: ``.ract/`` (``hooks``, ``novelty_budget.json``,
  ``rootknots.db``, ``sessions``, ``skills``, ``snapshots``) and one
  signed sidecar beside each file the run wrote;
- in the user state directory: ``ract/egress.jsonl``,
  ``ract/keys/<id>.pem`` (session and run keys) and ``ract/undo/...``.

No run writes ``evals/runs/<run_id>/events.jsonl`` or any report file.
This test keeps the short allowed list next to the assertions and fails
when a document claims a run creates anything outside it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The complete list of file or folder names a document may say a run
# creates. Measured per the docstring; extend only with a measured run.
ALLOWED_RUN_FILES = frozenset(
    {
        ".ract",
        ".ract/hooks",
        ".ract/novelty_budget.json",
        ".ract/rootknots.db",
        ".ract/sessions",
        ".ract/skills",
        ".ract/snapshots",
        ".NAME.rootknot.json",
        "egress.jsonl",
        "keys",
        "undo",
        "ract.yaml",
        "SPEC.md",
        ".ract/spec_hash.txt",
        ".ract/todo.json",
    }
)

# Names README once claimed a run creates that no writer uses.
RETIRED_REPORT_NAMES = (
    "mutation_kill.json",
    "patch_diff.json",
    "companion_report.json",
    "effort_reconciliation.json",
    "sycophancy.json",
    "investigator.json",
    "under_edit.json",
)


def _docs() -> list[Path]:
    return [
        REPO / "README.md",
        REPO / "docs" / "QUICKSTART.md",
        REPO / "docs" / "ARCHITECTURE.md",
    ]


def test_no_document_claims_a_run_creates_a_retired_report_name() -> None:
    for doc in _docs():
        for line in doc.read_text(encoding="utf-8").splitlines():
            if not re.search(r"run (writes|creates|gains)", line, re.I):
                continue
            for name in RETIRED_REPORT_NAMES:
                assert name not in line, (
                    f"{doc.name} claims a run creates {name}: {line.strip()!r}"
                )


def test_every_run_created_name_a_document_mentions_is_allowed() -> None:
    """Names near 'a run writes/creates/records' claims must be in the list."""
    claim = re.compile(
        r"(?:a run|every run|the run)[^\n.]{0,120}?`([^`]+)`", re.IGNORECASE
    )
    for doc in _docs():
        for line in doc.read_text(encoding="utf-8").splitlines():
            if not re.search(r"run (writes|creates|records|leaves)", line, re.I):
                continue
            for name in claim.findall(line):
                leaf = name.rstrip("/").split("/")[-1]
                stem = re.sub(r"^\.[^.]+\.", ".NAME.", leaf)
                assert (
                    name in ALLOWED_RUN_FILES
                    or leaf in ALLOWED_RUN_FILES
                    or stem in ALLOWED_RUN_FILES
                ), f"{doc.name}: {name!r} is not in the measured run-file list"


def test_the_trace_verbs_say_no_shipped_command_writes_a_log() -> None:
    from ract import cli_help

    assert "No shipped command writes one" in cli_help.VERB_DESCRIPTIONS["trace"]
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "No shipped command writes one in this build" in readme

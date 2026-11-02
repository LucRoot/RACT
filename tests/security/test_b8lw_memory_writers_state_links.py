"""Round-2 audit seam 6 (B-8lw): three memory writers guard their .ract writes.

``failure_records.write`` / ``failure_records.append_applied_narrowing``
appended a JSONL line through an unchecked path, and
``repo_fingerprint.write`` / the probe scheduler's
``write_capability_record`` wrote via mkstemp + os.replace with no
``workspace_state.check_state_path`` call -- although that function's
docstring says every writer of RACT's state calls it.  A repository
can ship ``.ract`` (or a folder under it) as a link or junction; the
failure-records append then lands in an arbitrary file, the exact
pattern B-213 was filed for.  The three modules now guard the resolved
state path like every other ``.ract`` writer.

This host cannot create symlinks; a directory junction (no privilege
on Windows) stands in, and the file-symlink case skips gracefully
where links are unavailable, as in tests/security/test_b213_state_links.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from ract.memory import failure_records, repo_fingerprint
from ract.memory.failure_records import (
    FAILURE_RECORDS_PATH,
    FailureRecord,
    NarrowingProposal,
)
from ract.memory.functions.testing import MockProvider
from ract.memory.probes.scheduler import (
    CAPABILITY_RECORD_PATH,
    read_capability_record,
    run_all_probes,
    write_capability_record,
)
from ract.memory.repo_fingerprint import FINGERPRINT_RECORD_PATH, RepoFingerprint
from ract.workspace_state import StateDirRefused


def _dir_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(
                f"no junction here: {done.stdout.strip()} {done.stderr.strip()}"
            )
    else:
        link.symlink_to(target, target_is_directory=True)


def _linked_project(tmp_path: Path, linked: str) -> tuple[Path, Path, Path]:
    """Project whose ``linked`` dir is a junction to ``outside``.

    Returns ``(root, outside, _)``: the caller computes where the
    writer's file lands when it follows the plant (``outside`` joined
    with the state path below the linked folder) and seeds it with a
    sentinel line so a write-through shows up as a change to that file.
    """
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    _dir_link(link, outside)
    return root, outside, link


def _assert_refused(write: Callable[[], Any], landing: Path, before: bytes) -> None:
    """The write must raise StateDirRefused and leave the plant untouched."""
    try:
        write()
    except StateDirRefused:
        pass
    else:
        pytest.fail(
            "write was not refused; it went through the plant into "
            f"{landing}: {landing.read_bytes()!r}"
        )
    assert landing.read_bytes() == before


def _record() -> FailureRecord:
    return FailureRecord(
        function="plan",
        input_token_count=1200,
        output_token_count=0,
        failure_type="budget_exceeded",
        resolution_level_reached="none",
        timestamp=1700000000,
    )


def _proposal() -> NarrowingProposal:
    return NarrowingProposal(
        function="plan",
        field_name="max_output_tokens",
        new_value=4000,
        reference_current_value=8000,
        reason="aggregation window shows repeated budget_exceeded",
    )


def _fingerprint() -> RepoFingerprint:
    return RepoFingerprint(
        avg_function_tokens=150.0,
        avg_import_depth=5.5,
        lsp_response_time_p50_ms=100,
        lsp_response_time_p95_ms=300,
        test_suite_runtime_seconds=60,
        commit_frequency_per_week=3.5,
        recorded_at=1700000000,
    )


@dataclass
class AlwaysHitProvider(MockProvider):
    """Provider that satisfies every probe (mirrors the module's own tests)."""

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        super().send(prompt, declaration)
        return "CROW: BLUE-42-ZULU tuesday wednesday"


def _reports() -> Any:
    return run_all_probes(AlwaysHitProvider())


# ---------------------------------------------------------------------------
# failure_records.write (append) and append_applied_narrowing (append)
# ---------------------------------------------------------------------------


@pytest.fixture(params=[".ract", ".ract/failures"])
def failures_linked(
    tmp_path: Path, request: pytest.FixtureRequest
) -> tuple[Path, Path, Path, bytes]:
    linked = request.param
    root, outside, _ = _linked_project(tmp_path, linked)
    landing = outside / FAILURE_RECORDS_PATH.relative_to(linked)
    landing.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b'{"sentinel": "victim file the repo planted"}\n'
    landing.write_bytes(sentinel)
    return root, outside, landing, sentinel


def test_a_failure_record_is_not_appended_through_a_linked_state_dir(
    failures_linked: tuple[Path, Path, Path, bytes],
) -> None:
    root, _, landing, sentinel = failures_linked
    _assert_refused(lambda: failure_records.write(_record(), root), landing, sentinel)


def test_an_applied_narrowing_is_not_appended_through_a_linked_state_dir(
    failures_linked: tuple[Path, Path, Path, bytes],
) -> None:
    root, outside, landing, sentinel = failures_linked
    landing_applied = landing.with_name("applied_narrowings.jsonl")
    landing_applied.write_bytes(sentinel)
    _assert_refused(
        lambda: failure_records.append_applied_narrowing(_proposal(), root),
        landing_applied,
        sentinel,
    )


def test_failure_records_write_refuses_a_symlink_at_the_records_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / ".ract" / "failures").mkdir(parents=True)
    victim = tmp_path / "victim.jsonl"
    victim.write_bytes(b"victim bytes\n")
    target = root / FAILURE_RECORDS_PATH
    try:
        os.symlink(victim, target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable here: {exc}")
    _assert_refused(
        lambda: failure_records.write(_record(), root), victim, b"victim bytes\n"
    )


def test_failure_records_write_appends_to_a_plain_existing_records_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    target = root / FAILURE_RECORDS_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"sentinel": "pre-existing records"}\n')
    result = failure_records.write(_record(), root)
    assert result == target
    lines = target.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"sentinel": "pre-existing records"}
    assert json.loads(lines[1]) == json.loads(
        json.dumps(
            {
                "function": "plan",
                "input_token_count": 1200,
                "output_token_count": 0,
                "failure_type": "budget_exceeded",
                "resolution_level_reached": "none",
                "timestamp": 1700000000,
            }
        )
    )


# ---------------------------------------------------------------------------
# repo_fingerprint.write (mkstemp + os.replace)
# ---------------------------------------------------------------------------


@pytest.fixture(params=[".ract", ".ract/fingerprint"])
def fingerprint_linked(
    tmp_path: Path, request: pytest.FixtureRequest
) -> tuple[Path, Path, Path, bytes]:
    linked = request.param
    root, outside, _ = _linked_project(tmp_path, linked)
    landing = outside / FINGERPRINT_RECORD_PATH.relative_to(linked)
    landing.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b'{"sentinel": "victim file the repo planted"}\n'
    landing.write_bytes(sentinel)
    return root, outside, landing, sentinel


def test_the_repo_fingerprint_is_not_written_through_a_linked_state_dir(
    fingerprint_linked: tuple[Path, Path, Path, bytes],
) -> None:
    root, _, landing, sentinel = fingerprint_linked
    _assert_refused(
        lambda: repo_fingerprint.write(_fingerprint(), root), landing, sentinel
    )


def test_repo_fingerprint_write_roundtrips_under_a_plain_ract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    fp = _fingerprint()
    target = repo_fingerprint.write(fp, root)
    assert target == root / FINGERPRINT_RECORD_PATH
    assert repo_fingerprint.read(root) == fp


# ---------------------------------------------------------------------------
# probes.scheduler.write_capability_record (mkstemp + os.replace)
# ---------------------------------------------------------------------------


@pytest.fixture(params=[".ract", ".ract/probes"])
def capability_linked(
    tmp_path: Path, request: pytest.FixtureRequest
) -> tuple[Path, Path, Path, bytes]:
    linked = request.param
    root, outside, _ = _linked_project(tmp_path, linked)
    landing = outside / CAPABILITY_RECORD_PATH.relative_to(linked)
    landing.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b'{"sentinel": "victim file the repo planted"}\n'
    landing.write_bytes(sentinel)
    return root, outside, landing, sentinel


def test_the_capability_record_is_not_written_through_a_linked_state_dir(
    capability_linked: tuple[Path, Path, Path, bytes],
) -> None:
    root, _, landing, sentinel = capability_linked
    reports = _reports()
    _assert_refused(lambda: write_capability_record(reports, root), landing, sentinel)


def test_capability_record_write_roundtrips_under_a_plain_ract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    reports = _reports()
    target = write_capability_record(reports, root)
    assert target == root / CAPABILITY_RECORD_PATH
    loaded = read_capability_record(root)
    assert loaded is not None
    assert loaded.usable_context_window == reports.needle.usable_context_window
    assert loaded.schema_version is not None

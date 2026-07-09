# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from rootact.consolidate import ConsolidationScanner, MergeProposal
from rootact.handshake_registry import HandshakeRegistry


def _write_module(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


IDENTICAL_BODY = """\
def helper():
    return 1


def another():
    data = [1, 2, 3, 4, 5]
    return sum(data)


class Thing:
    def __init__(self, value):
        self.value = value
"""


def test_scan_finds_near_duplicate_modules(tmp_path: Path) -> None:
    """Two modules with identical content should cluster together."""
    _write_module(tmp_path / "src" / "pkg" / "alpha.py", IDENTICAL_BODY)
    _write_module(tmp_path / "src" / "pkg" / "beta.py", IDENTICAL_BODY)
    _write_module(tmp_path / "src" / "pkg" / "__init__.py", "")
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert {proposal.target, *proposal.sources} == {
        "src/pkg/alpha.py",
        "src/pkg/beta.py",
    }
    assert proposal.safe is True


def test_scan_respects_max_modules(tmp_path: Path) -> None:
    """Only up to max_modules should be considered."""
    for i in range(5):
        _write_module(tmp_path / f"mod_{i}.py", f"def func_{i}():\n    return {i}\n")
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(max_modules=3)
    assert result.metrics["candidates"] == 3


def test_clustering_uses_average_linkage(tmp_path: Path) -> None:
    """Three modules where two are identical and one is different."""
    _write_module(tmp_path / "a.py", IDENTICAL_BODY)
    _write_module(tmp_path / "b.py", IDENTICAL_BODY)
    _write_module(
        tmp_path / "c.py",
        "def y():\n    return 'completely different content here'\n",
    )
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.target in {"a.py", "b.py"}
    assert set(proposal.sources) == {"a.py", "b.py"} - {proposal.target}
    assert "c.py" not in {proposal.target, *proposal.sources}


def test_pick_target_prefers_more_referenced_module(tmp_path: Path) -> None:
    """The target should be the module with more inbound references."""
    _write_module(
        tmp_path / "main.py", "from alpha import helper\nfrom beta import helper\n"
    )
    _write_module(tmp_path / "alpha.py", IDENTICAL_BODY)
    _write_module(tmp_path / "beta.py", IDENTICAL_BODY)
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    assert len(result.proposals) == 1
    # main.py is the consumer; alpha/beta are near-duplicates.
    proposal = result.proposals[0]
    assert proposal.target in {"alpha.py", "beta.py"}


def test_safety_check_rejects_cycle(tmp_path: Path) -> None:
    """A merge that would create a cycle is marked unsafe."""
    _write_module(
        tmp_path / "target.py", f"from source import helper\n{IDENTICAL_BODY}"
    )
    _write_module(tmp_path / "source.py", IDENTICAL_BODY)
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    assert len(result.proposals) == 1
    assert result.proposals[0].safe is False


def test_enqueue_proposals_creates_handshakes(tmp_path: Path) -> None:
    """Safe proposals are queued in the handshake registry."""
    _write_module(tmp_path / "a.py", IDENTICAL_BODY)
    _write_module(tmp_path / "b.py", IDENTICAL_BODY)
    scanner = ConsolidationScanner(tmp_path)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    registry = HandshakeRegistry(tmp_path)
    ids = scanner.enqueue_proposals(result, registry=registry)
    assert len(ids) == len(result.proposals)
    pending = registry.pending()
    assert len(pending) == 1
    assert pending[0].id == ids[0]


def test_merge_proposal_is_frozen() -> None:
    """MergeProposal must be immutable."""
    p = MergeProposal(target="a.py", sources=("b.py",), diff="", reason="test")
    with pytest.raises(AttributeError):
        p.target = "c.py"  # type: ignore[misc]


def test_cli_consolidate_dry_run(tmp_path: Path) -> None:
    """The CLI prints candidates in dry-run mode without enqueueing."""
    _write_module(tmp_path / "a.py", IDENTICAL_BODY)
    _write_module(tmp_path / "b.py", IDENTICAL_BODY)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "consolidate",
            "--project-dir",
            str(tmp_path),
            "--similarity-threshold",
            "0.50",
            "--merge-threshold",
            "0.50",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Found 1 consolidation proposal" in result.stdout
    assert "Dry run: no proposals enqueued." in result.stdout


def test_cli_consolidate_invalid_threshold(tmp_path: Path) -> None:
    """Threshold validation rejects out-of-range values."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "consolidate",
            "--project-dir",
            str(tmp_path),
            "--similarity-threshold",
            "1.5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "must be between 0.0 and 1.0" in result.stderr


# RACT 0.1.0 - Initial Public Release

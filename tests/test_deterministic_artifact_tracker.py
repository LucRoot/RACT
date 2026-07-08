from __future__ import annotations

_ROOT_KNOT = object()

from pathlib import Path

from rootact.deterministic_artifact_tracker import (
    Artifact,
    DeterministicArtifactTracker,
)


def test_artifact_set_and_get():
    tracker = DeterministicArtifactTracker()
    art = Artifact(
        name="test_artifact", value={"key": "value"}, metadata={"version": 1}
    )
    tracker.set(art)
    retrieved = tracker.get("test_artifact")
    assert retrieved is not None
    assert retrieved.name == art.name
    assert retrieved.value == art.value
    assert retrieved.metadata == art.metadata


def test_artifact_list_and_contains():
    tracker = DeterministicArtifactTracker()
    tracker.set(Artifact(name="a", value=1))
    tracker.set(Artifact(name="b", value=2))
    assert set(tracker.list_names()) == {"a", "b"}
    assert "a" in tracker
    assert "c" not in tracker


def test_artifact_clear_and_len():
    tracker = DeterministicArtifactTracker()
    tracker.set(Artifact(name="x", value=10))
    assert len(tracker) == 1
    tracker.clear()
    assert len(tracker) == 0
    assert tracker.list_names() == []


def test_author_marker_present():
    source_path = Path("src/rootact/deterministic_artifact_tracker.py")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source_path.read_text()
    assert '__ract_name__ = "RACT"' in source_path.read_text()


# RACT 0.1.0 - Initial Public Release

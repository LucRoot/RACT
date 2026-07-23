__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import os

from rootact.artifact_store import (
    Artifact,
    ArtifactStore,
    TemporaryFileManager,
    deserialize_artifact,
    serialize_artifact,
    simple_checksum,
)


def test_artifact_fields():
    artifact = Artifact(
        name="test_artifact", path="/tmp/test", size_bytes=1024, checksum="abc123"
    )
    assert artifact.name == "test_artifact"
    assert artifact.path == "/tmp/test"
    assert artifact.size_bytes == 1024
    assert artifact.checksum == "abc123"


def test_artifact_store_add_and_get():
    store = ArtifactStore()
    artifact = Artifact(
        name="test_artifact", path="/tmp/test", size_bytes=1024, checksum="abc123"
    )
    store.add(artifact)
    retrieved = store.get("test_artifact")
    assert retrieved is not None
    assert retrieved.name == "test_artifact"
    assert retrieved.path == "/tmp/test"
    assert retrieved.size_bytes == 1024
    assert retrieved.checksum == "abc123"


def test_artifact_store_get_missing_returns_none():
    store = ArtifactStore()
    assert store.get("missing") is None


def test_artifact_store_list_names():
    store = ArtifactStore()
    names = ["a", "b", "c"]
    for name in names:
        store.add(Artifact(name=name, path="/tmp", size_bytes=0, checksum="0"))
    assert sorted(store.list_names()) == sorted(names)


def test_artifact_store_clear():
    store = ArtifactStore()
    store.add(Artifact(name="test", path="/tmp", size_bytes=0, checksum="0"))
    store.clear()
    assert store.list_names() == []
    assert store.get("test") is None


def test_artifact_store_overwrite_existing_name():
    store = ArtifactStore()
    store.add(Artifact(name="x", path="/a", size_bytes=1, checksum="1"))
    store.add(Artifact(name="x", path="/b", size_bytes=2, checksum="2"))
    retrieved = store.get("x")
    assert retrieved.path == "/b"
    assert retrieved.size_bytes == 2


def test_temporary_file_manager_creates_and_cleans_up():
    with TemporaryFileManager(suffix=".txt") as manager:
        manager.create()
        path = manager.tempfile.name
        assert os.path.exists(path)
        manager.tempfile.write("hello")
        manager.tempfile.flush()
    assert not os.path.exists(path)


def test_temporary_file_manager_write_content():
    with TemporaryFileManager(suffix=".txt") as manager:
        manager.create()
        manager.tempfile.write("test content")
        manager.tempfile.flush()
        manager.tempfile.seek(0)
        assert manager.tempfile.read() == "test content"


def test_temporary_file_manager_ignores_missing_file_on_cleanup():
    with TemporaryFileManager(suffix=".txt") as manager:
        manager.create()
        path = manager.tempfile.name
        assert os.path.exists(path)
        manager.tempfile.close()
        os.unlink(path)  # remove early so __exit__ hits the OSError branch
    assert not os.path.exists(path)


def test_simple_checksum_empty_bytes():
    assert simple_checksum(b"") == "0" * 8


def test_simple_checksum_non_empty_bytes():
    data = b"hello"
    expected = str(sum(data) % 1_000_000_007)
    assert simple_checksum(data) == expected


def test_simple_checksum_different_data_different_checksum():
    assert simple_checksum(b"a") != simple_checksum(b"b")


def test_serialize_artifact():
    artifact = Artifact(name="a", path="/p", size_bytes=10, checksum="c")
    raw = serialize_artifact(artifact)
    obj = json.loads(raw)
    assert obj == {"name": "a", "path": "/p", "size_bytes": 10, "checksum": "c"}


def test_deserialize_artifact():
    raw = json.dumps({"name": "a", "path": "/p", "size_bytes": 10, "checksum": "c"})
    artifact = deserialize_artifact(raw)
    assert artifact.name == "a"
    assert artifact.path == "/p"
    assert artifact.size_bytes == 10
    assert artifact.checksum == "c"


def test_serialize_deserialize_round_trip():
    original = Artifact(name="round", path="/trip", size_bytes=42, checksum="abc")
    restored = deserialize_artifact(serialize_artifact(original))
    assert restored == original


# RACT 0.1.2 - Trust and tooling

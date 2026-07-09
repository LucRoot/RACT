__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest
from rootact.artifact_store import Artifact, ArtifactStore


class TestArtifact(unittest.TestCase):
    def test_artifact_creation(self):
        artifact = Artifact(
            name="test_artifact", path="/tmp/test", size_bytes=1024, checksum="abc123"
        )
        self.assertEqual(artifact.name, "test_artifact")
        self.assertEqual(artifact.path, "/tmp/test")
        self.assertEqual(artifact.size_bytes, 1024)
        self.assertEqual(artifact.checksum, "abc123")


class TestArtifactStore(unittest.TestCase):
    def setUp(self):
        self.store = ArtifactStore()

    def test_add_and_get(self):
        artifact = Artifact(
            name="test_artifact", path="/tmp/test", size_bytes=1024, checksum="abc123"
        )
        self.store.add(artifact)
        retrieved = self.store.get("test_artifact")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test_artifact")

    def test_list_names(self):
        names = ["a", "b", "c"]
        for name in names:
            self.store.add(Artifact(name=name, path="/tmp", size_bytes=0, checksum="0"))
        self.assertCountEqual(self.store.list_names(), names)

    def test_clear(self):
        self.store.add(Artifact(name="test", path="/tmp", size_bytes=0, checksum="0"))
        self.store.clear()
        self.assertEqual(len(self.store.list_names()), 0)


if __name__ == "__main__":
    unittest.main()
# RACT 0.1.1 - Trust and tooling

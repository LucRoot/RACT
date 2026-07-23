import unittest

from ract.artifact_tracker import ArtifactTracker, TrackedArtifact


class TestArtifactTracker(unittest.TestCase):
    def test_register_and_contains(self):
        tracker = ArtifactTracker()
        artifact = TrackedArtifact(
            identifier="abc123", checksum="sha256:123", path="/tmp/abc123"
        )
        tracker.register(artifact)
        self.assertTrue(tracker.contains("abc123"))
        self.assertIsNone(tracker.get("missing"))

    def test_get_and_list_identifiers(self):
        tracker = ArtifactTracker()
        a1 = TrackedArtifact("id1", "cs1", "/p1")
        a2 = TrackedArtifact("id2", "cs2", "/p2")
        tracker.register(a1)
        tracker.register(a2)
        self.assertEqual(tracker.list_identifiers(), {"id1", "id2"})
        self.assertEqual(tracker.get("id1"), a1)


# RACT 0.1.1 - Trust and tooling

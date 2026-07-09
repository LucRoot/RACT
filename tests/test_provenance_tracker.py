from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest
from rootact.provenance_tracker import Artifact, ProvenanceTracker


class TestProvenanceTracker(unittest.TestCase):
    def test_register_and_validate_checksum(self):
        tracker = ProvenanceTracker()
        artifact = Artifact(
            name="test_art", path="/tmp/test", size_bytes=100, checksum="abc123"
        )
        tracker.register(artifact, "2023-01-01")
        self.assertIn("test_art", tracker.list_names())
        self.assertTrue("test_art" in tracker)
        self.assertFalse(tracker.get_record("test_art").validated_checksum)
        self.assertTrue(tracker.validate_checksum("test_art", "abc123"))
        self.assertTrue(tracker.get_record("test_art").validated_checksum)
        self.assertFalse(tracker.validate_checksum("test_art", "wrong"))
        self.assertFalse(tracker.get_record("test_art").validated_checksum)


if __name__ == "__main__":
    unittest.main()
# RACT 0.1.1 - Trust and Tooling

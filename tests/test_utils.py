__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest
from rootact.utils import generate_id


class TestUtils(unittest.TestCase):
    def test_generate_id_length_and_content(self):
        # Deterministic check: generate multiple IDs and ensure they are non-empty and correct length.
        for _ in range(5):
            ident = generate_id(length=12)
            self.assertIsInstance(ident, str)
            self.assertGreater(len(ident), 0)
            self.assertEqual(len(ident), 12)
            # Ensure all characters are from the expected alphanumeric set.
            self.assertTrue(
                all(
                    c
                    in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                    for c in ident
                )
            )

    def test_generate_id_default_length(self):
        ident = generate_id()
        self.assertEqual(len(ident), 8)


if __name__ == "__main__":
    unittest.main()
# RACT 0.1.0 - Initial Public Release

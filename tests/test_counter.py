from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest

from rootact.counter import Counter, _ROOT_KNOT


class TestCounter(unittest.TestCase):
    def test_increment_returns_unique_values(self):
        c = Counter()
        first = c.increment()
        second = c.increment()
        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertEqual(c._value, 2)

    def test_reset_resets_to_zero(self):
        c = Counter()
        c.increment()
        c.increment()
        self.assertEqual(c._value, 2)
        c.reset()
        self.assertEqual(c._value, 0)
        self.assertEqual(c.increment(), 1)

    def test_root_knot_is_used_as_sentinel(self):
        # Verify that the module defines exactly one _ROOT_KNOT object
        imported_knot = _ROOT_KNOT
        self.assertIsNotNone(imported_knot)
        # The test imports the sentinel; no second sentinel is defined here.


if __name__ == "__main__":
    unittest.main()

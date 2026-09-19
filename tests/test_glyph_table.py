"""Unit tests for bitmask glyph table definitions."""

import unittest

from recognition.glyph_table import (
    ALL_PROTOTYPES,
    EXACT_GLYPHS,
)


class TestGlyphTable(unittest.TestCase):
    """Tests for bitmask prototype tables integrity."""

    def test_exact_glyphs_loaded(self):
        """Verify exact glyph table contains over 800 bitmask entries."""
        self.assertGreater(len(EXACT_GLYPHS), 800)

    def test_all_prototypes_keys(self):
        """Verify prototype entries exist and have valid widths."""
        self.assertGreater(len(ALL_PROTOTYPES), 20)
        for d, tb, tw in ALL_PROTOTYPES:
            self.assertGreater(tw, 0)
            self.assertEqual(len(tb), 10)


if __name__ == "__main__":
    unittest.main()

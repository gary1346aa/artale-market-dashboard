"""Unit tests for visualization theme, typography, and tick math."""

import unittest

from visualization.theme import (
    calc_nice_ticks,
    format_axis_price,
    format_price_cjk,
    format_vol_cjk,
)


class TestVisualization(unittest.TestCase):
    """Tests for financial price formatting and axis tick generation."""

    def test_format_price_cjk(self):
        """Format numbers into human-readable Chinese currency strings (億, 萬)."""
        self.assertEqual(format_price_cjk(638000000), "6.38 億")
        self.assertEqual(format_price_cjk(2800000), "280.0 萬")
        self.assertEqual(format_price_cjk(4500), "4,500")
        self.assertEqual(format_price_cjk(0), "0")
        self.assertEqual(format_price_cjk(None), "-")

    def test_format_axis_price(self):
        """Format Y-axis prices with rounding and badge indicators."""
        self.assertEqual(format_axis_price(3000000, is_badge=False), "300 萬")
        self.assertEqual(format_axis_price(2767000, is_badge=True), "276.7 萬")
        self.assertEqual(format_axis_price(450000000, is_badge=False), "4.5 億")

    def test_format_vol_cjk(self):
        """Format trade volumes with comma separators and Chinese suffix."""
        self.assertEqual(format_vol_cjk(1250), "1,250 件")
        self.assertEqual(format_vol_cjk(0), "0 件")

    def test_calc_nice_ticks(self):
        """Calculate clean round axis tick values spanning data range."""
        ticks, n_min, n_max = calc_nice_ticks(2000000, 3000000, target_ticks=5)
        self.assertGreaterEqual(len(ticks), 3)
        self.assertLessEqual(n_min, 2000000)
        self.assertGreaterEqual(n_max, 3000000)


if __name__ == "__main__":
    unittest.main()

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


class TestKlinePlotter24hSummary(unittest.TestCase):
    """Tests for 24h rolling summary metrics in kline_plotter."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from storage.database import init_db
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_kline.db"
        init_db(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_get_24h_summary_calculation(self):
        """Verify 24h metrics only aggregate the rolling 24-hour window."""
        import sqlite3
        from visualization.kline_plotter import get_24h_summary

        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            candles = [
                # item, tf, bucket_time, open, high, low, close, vol, turnover, vwap, trades
                # Global latest is 2026-09-22 12:00:00
                ("ItemA", "1h", "2026-09-20 10:00:00", 100, 110, 95, 105, 50, 5250, 105.0, 5),  # > 24h ago
                ("ItemA", "1h", "2026-09-21 13:00:00", 100, 115, 98, 110, 20, 2200, 110.0, 2),  # 23h ago (open is 100)
                ("ItemA", "1h", "2026-09-22 12:00:00", 110, 125, 108, 120, 30, 3600, 120.0, 3), # 0h ago (close is 120)
                # Item B: stale item
                ("ItemB", "1h", "2026-09-18 08:00:00", 500, 520, 490, 510, 100, 51000, 510.0, 10),
            ]
            c.executemany(
                """
                INSERT INTO kline_candles (
                    item_name, timeframe, bucket_time, open_price, high_price,
                    low_price, close_price, volume, turnover, vwap, trade_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                candles,
            )

        summary_a = get_24h_summary("ItemA", db_path=self.db_path)
        self.assertEqual(summary_a["vol_24"], 50)
        self.assertEqual(summary_a["turnover_24"], 5800)
        self.assertEqual(summary_a["high_24"], 125)
        self.assertEqual(summary_a["low_24"], 98)
        self.assertEqual(summary_a["latest_price"], 120)
        # chg_24: (120 - 100) / 100 * 100 = 20.0%
        self.assertAlmostEqual(summary_a["chg_24"], 20.0)
        # vwap_24: 5800 / 50 = 116.0
        self.assertAlmostEqual(summary_a["vwap_24"], 116.0)

        # Stale item
        summary_b = get_24h_summary("ItemB", db_path=self.db_path)
        self.assertEqual(summary_b["vol_24"], 0)
        self.assertEqual(summary_b["turnover_24"], 0)
        self.assertEqual(summary_b["high_24"], 510)
        self.assertEqual(summary_b["low_24"], 510)
        self.assertEqual(summary_b["latest_price"], 510)
        self.assertEqual(summary_b["chg_24"], 0.0)

        # Non-existent item
        summary_c = get_24h_summary("NonExistent", db_path=self.db_path)
        self.assertEqual(summary_c["vol_24"], 0)
        self.assertEqual(summary_c["turnover_24"], 0)
        self.assertEqual(summary_c["latest_price"], 0)


if __name__ == "__main__":
    unittest.main()

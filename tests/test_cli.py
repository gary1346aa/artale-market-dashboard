"""Unit tests for command line interfaces."""

import argparse
import unittest
from unittest.mock import patch

from cli.query import handle_trades, handle_listings


class TestCli(unittest.TestCase):
    """Tests for CLI handlers."""

    @patch("builtins.print")
    @patch("cli.query.fetch_recent_trades")
    def test_handle_trades_empty(self, mock_fetch, mock_print):
        """Handle trades query when no trades exist."""
        mock_fetch.return_value = []
        args = argparse.Namespace(item="測試道具", limit=10)
        handle_trades(args)
        mock_print.assert_called()

    @patch("builtins.print")
    @patch("cli.query.fetch_active_listings")
    def test_handle_listings_empty(self, mock_fetch, mock_print):
        """Handle listings query when no listings exist."""
        mock_fetch.return_value = []
        args = argparse.Namespace(item="測試道具", limit=10)
        handle_listings(args)
        mock_print.assert_called()


if __name__ == "__main__":
    unittest.main()

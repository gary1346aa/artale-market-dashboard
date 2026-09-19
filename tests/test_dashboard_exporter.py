"""Unit tests for dashboard data export and HTML generation."""

import tempfile
import unittest
from pathlib import Path

from storage.database import init_db
from visualization.dashboard_exporter import export_dashboard_data


class TestDashboardExporter(unittest.TestCase):
    """Tests for dashboard payload generation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_dash.db"
        init_db(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_export_dashboard_data_empty_db(self):
        """Export dashboard data structure from empty DB without crashing."""
        data = export_dashboard_data(db_path=self.db_path)
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertIn("data", data)


if __name__ == "__main__":
    unittest.main()

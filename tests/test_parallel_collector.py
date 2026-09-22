"""Unit tests for ParallelCollector autonomous per-instance lifecycle and queue draining."""

import unittest
from unittest.mock import MagicMock, patch

from pipeline.parallel_collector import ParallelCollector


class TestParallelCollector(unittest.TestCase):
    """Tests for ParallelCollector initialization and worker lifecycle."""

    def test_init_with_explicit_instances(self):
        """Verify initialization maps explicit instance names to devices."""
        collector = ParallelCollector(
            instances=["槍手", "打火機"],
            use_adb=True,
            cold_boot=False,
            bootstrap=False,
        )
        self.assertEqual(len(collector.worker_targets), 2)
        inst_names = [inst for inst, _ in collector.worker_targets]
        self.assertIn("槍手", inst_names)
        self.assertIn("打火機", inst_names)

    def test_init_with_max_workers_limit(self):
        """Verify max_workers caps the number of worker targets."""
        collector = ParallelCollector(
            instances=["槍手", "打火機", "弩手"],
            max_workers=1,
            use_adb=True,
        )
        self.assertEqual(len(collector.worker_targets), 1)

    @patch("pipeline.parallel_collector.MarketCollector")
    @patch("pipeline.parallel_collector.GameBootstrapper")
    def test_worker_lifecycle_scan_and_kill(self, mock_bootstrapper_cls, mock_collector_cls):
        """Verify worker bootstraps, drains queue, and terminates instance if kill_after=True."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_running.return_value = False
        mock_ctrl.trigger_launch.return_value = True
        mock_ctrl.wait_for_ready.return_value = True

        mock_bootstrapper = MagicMock()
        mock_bootstrapper.bootstrap_to_free_market.return_value = True
        mock_bootstrapper_cls.return_value = mock_bootstrapper

        mock_market_collector = MagicMock()
        mock_market_collector.ensure_focus.return_value = True
        mock_market_collector.get_screen_quota.return_value = 50
        mock_market_collector.run_query_collection.return_value = True
        mock_collector_cls.return_value = mock_market_collector

        collector = ParallelCollector(
            instances=["槍手"],
            use_adb=True,
            cold_boot=True,
            bootstrap=True,
            kill_after=True,
            controller=mock_ctrl,
        )

        with patch("pipeline.parallel_collector.time.sleep"):
            collector.run_catalog_scan(["ItemA", "ItemB"], max_pages=1, target_tab="both")

        # Verify launch dispatched and waited
        mock_ctrl.trigger_launch.assert_called_with("槍手")
        mock_ctrl.wait_for_ready.assert_called_with("槍手", max_wait_sec=60)

        # Verify bootstrap called
        mock_bootstrapper.bootstrap_to_free_market.assert_called_once()

        # Verify items collected
        self.assertEqual(mock_market_collector.run_query_collection.call_count, 2)

        # Verify instance cleanly quit after batch completion
        mock_ctrl.quit_instance.assert_called_with("槍手")

    @patch("pipeline.parallel_collector.MarketCollector")
    def test_worker_quota_exhaustion_requeues_item(self, mock_collector_cls):
        """Verify exhausted worker returns current item to queue and terminates."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_running.return_value = True

        mock_market_collector = MagicMock()
        mock_market_collector.ensure_focus.return_value = True
        mock_market_collector.get_screen_quota.return_value = 50
        # First call fails due to quota exhaustion
        mock_market_collector.run_query_collection.return_value = False
        mock_collector_cls.return_value = mock_market_collector

        collector = ParallelCollector(
            instances=["槍手"],
            use_adb=True,
            cold_boot=False,
            bootstrap=False,
            kill_after=True,
            controller=mock_ctrl,
        )

        with patch("pipeline.parallel_collector.time.sleep"):
            collector.run_catalog_scan(["ItemA"], max_pages=1, target_tab="both")

        mock_market_collector.leave_auction.assert_called_once()
        mock_ctrl.quit_instance.assert_called_with("槍手")


if __name__ == "__main__":
    unittest.main()

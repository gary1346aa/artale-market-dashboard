"""Unit tests for GameBootstrapper and dynamic Artale card detection."""

import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from driver.game_bootstrapper import (
    GameBootstrapper,
    MSW_PACKAGE_NAME,
    find_artale_card_coordinates,
)


class TestGameBootstrapper(unittest.TestCase):
    """Tests for game bootstrap automation and card OCR filtering."""

    @patch("winocr.recognize_pil_sync")
    def test_find_artale_card_normal_order(self, mock_winocr):
        """Card detection locates Artale (繁體中文版) and ignores Lounge."""
        mock_winocr.return_value = {
            "lines": [
                {
                    "text": "Artale Lounge (繁體中文版)",
                    "words": [
                        {
                            "text": "Lounge",
                            "bounding_rect": {"x": 100.0, "y": 430.0, "width": 80.0, "height": 20.0},
                        }
                    ],
                },
                {
                    "text": "Artale (繁體中文版)",
                    "words": [
                        {
                            "text": "繁",
                            "bounding_rect": {"x": 520.0, "y": 432.0, "width": 24.0, "height": 24.0},
                        },
                        {
                            "text": "體",
                            "bounding_rect": {"x": 545.0, "y": 432.0, "width": 24.0, "height": 24.0},
                        },
                    ],
                },
            ]
        }
        dummy = Image.new("RGB", (720, 1280))
        coords = find_artale_card_coordinates(dummy)
        self.assertIsNotNone(coords)
        self.assertEqual(coords, (532, 312))

    @patch("winocr.recognize_pil_sync")
    def test_find_artale_card_reversed_order(self, mock_winocr):
        """Card detection works when card positions are swapped (Artale on left)."""
        mock_winocr.return_value = {
            "lines": [
                {
                    "text": "Artale (繁體中文版)",
                    "words": [
                        {
                            "text": "繁",
                            "bounding_rect": {"x": 120.0, "y": 430.0, "width": 24.0, "height": 24.0},
                        }
                    ],
                },
                {
                    "text": "Artale Lounge",
                    "words": [
                        {
                            "text": "Lounge",
                            "bounding_rect": {"x": 500.0, "y": 430.0, "width": 80.0, "height": 20.0},
                        }
                    ],
                },
            ]
        }
        dummy = Image.new("RGB", (720, 1280))
        coords = find_artale_card_coordinates(dummy)
        self.assertIsNotNone(coords)
        self.assertEqual(coords, (132, 310))

    @patch("winocr.recognize_pil_sync")
    def test_find_artale_card_no_match(self, mock_winocr):
        """Returns None if no matching tokens exist."""
        mock_winocr.return_value = {"lines": []}
        dummy = Image.new("RGB", (720, 1280))
        coords = find_artale_card_coordinates(dummy)
        self.assertIsNone(coords)

    def test_return_home_and_cleanup(self):
        """Verifies force-stop, HOME key, and ESC popup dismissals."""
        mock_adb = MagicMock()
        mock_ctrl = MagicMock()
        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")

        bootstrapper.return_home_and_cleanup()
        mock_adb._run_adb.assert_called_with("shell", "am", "force-stop", MSW_PACKAGE_NAME)
        mock_adb.keyevent.assert_called_with(3)
        mock_adb.send_esc.assert_called_with(count=4, delay_sec=0.4)

    def test_restart_instance_clean(self):
        """Verifies clean reboot shuts down, relaunches, and sends ESC."""
        mock_adb = MagicMock()
        mock_ctrl = MagicMock()
        mock_ctrl.launch_instance.return_value = True

        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")
        res = bootstrapper.restart_instance_clean()

        self.assertTrue(res)
        mock_ctrl.quit_instance.assert_called_once_with("槍手")
        mock_ctrl.launch_instance.assert_called_once_with("槍手", max_wait_sec=60)
        mock_adb.send_esc.assert_called_once_with(count=4, delay_sec=0.5)

    def test_bootstrap_short_circuits_if_already_in_free_market(self):
        """Short-circuits immediately if already in Free Market."""
        mock_adb = MagicMock()
        mock_adb.is_free_market.return_value = True
        mock_ctrl = MagicMock()

        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")
        self.assertTrue(bootstrapper.bootstrap_to_free_market())
        mock_adb.tap.assert_not_called()

    @patch("time.sleep")
    def test_screencap_recovers_after_backoff_and_reconnect(self, mock_sleep):
        """Simulates 2 consecutive screencap failures (2s, 4s backoff + reconnect), then recovery."""
        mock_adb = MagicMock()
        mock_adb.is_free_market.return_value = False
        # Fails twice (None, None), then returns valid frame, then Free Market frame
        fm_frame = Image.new("RGB", (720, 1280))
        mock_adb.screencap.side_effect = [None, None, fm_frame]

        mock_ctrl = MagicMock()
        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")

        with patch("driver.game_bootstrapper.detect_screen_state") as mock_detect:
            from driver.game_bootstrapper import ScreenState
            mock_detect.side_effect = [ScreenState.UNKNOWN, ScreenState.UNKNOWN, ScreenState.STATE_FREE_MARKET]
            res = bootstrapper.bootstrap_to_free_market(max_timeout_sec=60)

        self.assertTrue(res)
        # Attempt 1 backoff: 2s, Attempt 2 backoff: 4s + reconnect
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)
        mock_adb.reconnect.assert_called_once()
        mock_ctrl.quit_instance.assert_not_called()

    @patch("time.sleep")
    def test_screencap_freeze_confirmed_after_20s_backoff(self, mock_sleep):
        """Confirms freeze triggers restart after exhausting 20s backoff (2+4+6+8s)."""
        mock_adb = MagicMock()
        mock_adb.is_free_market.return_value = False
        # 5 consecutive failures
        mock_adb.screencap.return_value = None

        mock_ctrl = MagicMock()
        mock_ctrl.launch_instance.return_value = True

        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")

        with patch.object(bootstrapper, "restart_instance_clean", return_value=False) as mock_restart:
            res = bootstrapper.bootstrap_to_free_market(max_timeout_sec=60)
            self.assertFalse(res)
            mock_restart.assert_called_once()

        # Verify backoff sleeps: 2s, 4s, 6s, 8s
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)
        mock_sleep.assert_any_call(6.0)
        mock_sleep.assert_any_call(8.0)
        mock_adb.reconnect.assert_called_once()

    @patch("time.sleep")
    def test_unknown_screen_state_no_unnecessary_logs(self, mock_sleep):
        """Verifies Unknown screen state is not logged during retries."""
        from driver.game_bootstrapper import ScreenState

        mock_adb = MagicMock()
        mock_adb.is_free_market.return_value = False
        frame = Image.new("RGB", (720, 1280))
        mock_adb.screencap.return_value = frame

        mock_ctrl = MagicMock()
        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="槍手")

        with patch("driver.game_bootstrapper.detect_screen_state", return_value=ScreenState.UNKNOWN), \
             patch("driver.game_bootstrapper._logger") as mock_logger, \
             patch.object(bootstrapper, "restart_instance_clean", return_value=False):
            res = bootstrapper.bootstrap_to_free_market(max_timeout_sec=0)
            self.assertFalse(res)

        # Unknown screen state log should not be called
        all_logs = [str(call) for call in mock_logger.mock_calls if "Unknown screen state" in str(call)]
        self.assertEqual(all_logs, [])

    @patch("time.sleep")
    def test_respawn_resets_timeout_timer(self, mock_sleep):
        """Verifies that respawning an instance resets start_t so bootstrap doesn't prematurely time out."""
        from driver.game_bootstrapper import ScreenState

        mock_adb = MagicMock()
        mock_adb.is_free_market.return_value = False
        frame = Image.new("RGB", (720, 1280))
        mock_adb.screencap.return_value = frame

        mock_ctrl = MagicMock()
        bootstrapper = GameBootstrapper(mock_adb, controller=mock_ctrl, instance_name="弩手")

        # Simulate time progression:
        # T=1000: start_t initialized
        # T=1005..1040: 8 unknown cycles to trigger respawn
        # T=1055: inside respawn, start_t should be reset to 1055
        # T=1060: next cycle, elapsed from 1055 is only 5s (well within max_timeout_sec=60)
        # Without reset: 1060 - 1000 = 60s -> would time out!
        times = [
            1000.0,  # initial start_t
            1010.0,  # iteration 1 check (unknown 1)
            1020.0,  # iteration 2 check (unknown 2)
            1030.0,  # iteration 3 check (unknown 3 -> triggers respawn)
            1070.0,  # inside respawn: reset start_t = 1070.0
            1075.0,  # iteration 4 check: 1075 - 1070 = 5s (without reset: 1075 - 1000 = 75s > 60s)
        ]
        time_iter = iter(times)

        def mock_time():
            try:
                return next(time_iter)
            except StopIteration:
                return 2000.0

        states = [
            ScreenState.UNKNOWN,
            ScreenState.UNKNOWN,
            ScreenState.UNKNOWN,
            ScreenState.STATE_FREE_MARKET,
        ]

        with patch("driver.game_bootstrapper.MAX_CONSECUTIVE_UNKNOWNS", 3), \
             patch("time.time", side_effect=mock_time), \
             patch("driver.game_bootstrapper.detect_screen_state", side_effect=states), \
             patch.object(bootstrapper, "restart_instance_clean", return_value=True) as mock_restart:
            res = bootstrapper.bootstrap_to_free_market(max_timeout_sec=60)
            self.assertTrue(res)
            mock_restart.assert_called_once()


if __name__ == "__main__":
    unittest.main()

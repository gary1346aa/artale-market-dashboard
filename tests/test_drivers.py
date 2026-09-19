"""Unit tests for low-level device and emulator drivers."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from driver.emulator_controller import EmulatorController
from driver.window_driver import enable_dpi_awareness


class TestDrivers(unittest.TestCase):
    """Tests for emulator controller commands and window drivers."""

    @patch("subprocess.run")
    def test_emulator_is_running_true(self, mock_run):
        """Verify is_running returns True when ldconsole reports 'running'."""
        mock_proc = MagicMock()
        mock_proc.stdout = "running\n"
        mock_run.return_value = mock_proc

        controller = EmulatorController(ldconsole_path="fake_ldconsole.exe")
        self.assertTrue(controller.is_running("LDPlayer-1"))
        mock_run.assert_called_once_with(
            ["fake_ldconsole.exe", "isrunning", "--name", "LDPlayer-1"],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("subprocess.run")
    def test_emulator_is_running_false(self, mock_run):
        """Verify is_running returns False when ldconsole reports 'stop'."""
        mock_proc = MagicMock()
        mock_proc.stdout = "stop\n"
        mock_run.return_value = mock_proc

        controller = EmulatorController(ldconsole_path="fake_ldconsole.exe")
        self.assertFalse(controller.is_running("LDPlayer-1"))

    @patch("subprocess.run")
    def test_emulator_quit_instance(self, mock_run):
        """Verify quit_instance issues quit command via ldconsole."""
        controller = EmulatorController(ldconsole_path="fake_ldconsole.exe")
        controller.quit_instance("LDPlayer-2")
        mock_run.assert_called_once_with(
            ["fake_ldconsole.exe", "quit", "--name", "LDPlayer-2"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_enable_dpi_awareness_safe(self):
        """Verify enable_dpi_awareness executes safely without uncaught exceptions."""
        # Should execute safely on Windows or gracefully pass on mock
        try:
            enable_dpi_awareness()
        except Exception as e:
            self.fail(f"enable_dpi_awareness raised an unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()

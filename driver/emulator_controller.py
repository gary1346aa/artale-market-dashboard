"""LDPlayer emulator lifecycle controller.

Wraps ldconsole.exe commands to query, launch, reboot, or close Android
emulator instances programmatically.
"""

import logging
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Union

from config.settings import DEFAULT_LDCONSOLE

_logger = logging.getLogger(__name__)


class EmulatorController:
    """Manages LDPlayer instance lifecycle via ldconsole.

    Attributes:
        ldconsole_path: Path to ldconsole.exe binary.
    """

    def __init__(
        self, ldconsole_path: Union[str, Path] = DEFAULT_LDCONSOLE
    ) -> None:
        """Initializes EmulatorController with ldconsole executable path."""
        self.ldconsole_path = str(ldconsole_path)

    def is_running(self, instance_name: str) -> bool:
        """Checks if an LDPlayer instance is currently running.

        Args:
            instance_name: Name of the emulator instance (e.g. 'LDPlayer-1').

        Returns:
            True if instance is running, False otherwise.
        """
        try:
            res = subprocess.run(
                [self.ldconsole_path, "isrunning", "--name", instance_name],
                capture_output=True,
                text=True,
                check=False,
            )
            return res.stdout.strip() == "running"
        except Exception as err:
            _logger.error(
                "Error checking instance state for '%s': %s",
                instance_name,
                err,
            )
            return False

    def launch_instance(
        self, instance_name: str, max_wait_sec: int = 50
    ) -> bool:
        """Boots the instance via ldconsole and waits for Android OS to stabilize.

        Args:
            instance_name: Name of the instance to boot.
            max_wait_sec: Maximum seconds to wait for boot completion.

        Returns:
            True if successfully booted, False if timed out.
        """
        if self.is_running(instance_name):
            _logger.info("Instance '%s' is already running.", instance_name)
            return True

        _logger.info("Booting LDPlayer instance '%s'...", instance_name)
        subprocess.run(
            [self.ldconsole_path, "launch", "--name", instance_name],
            capture_output=True,
            text=True,
            check=False,
        )

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            if self.is_running(instance_name):
                _logger.info(
                    "Instance '%s' running. Waiting 15s for OS to settle...",
                    instance_name,
                )
                time.sleep(15)
                return True
            time.sleep(2)

        _logger.error("Timed out waiting for '%s' to boot.", instance_name)
        return False

    def quit_instance(self, instance_name: str) -> bool:
        """Terminates an LDPlayer instance via ldconsole.

        Args:
            instance_name: Name of the instance to quit.

        Returns:
            True on successful command execution.
        """
        try:
            subprocess.run(
                [self.ldconsole_path, "quit", "--name", instance_name],
                capture_output=True,
                text=True,
                check=False,
            )
            return True
        except Exception as err:
            _logger.error("Error quitting instance '%s': %s", instance_name, err)
            return False

    def list_instances(self) -> List[Dict[str, Any]]:
        """Lists all registered LDPlayer instances and their statuses.

        Returns:
            List of dicts containing 'index', 'name', 'top_hwnd', 'bind_hwnd',
            'is_running', 'pid', 'vbox_pid'.
        """
        try:
            res = subprocess.run(
                [self.ldconsole_path, "list2"],
                capture_output=True,
                text=True,
                check=False,
            )
            instances: List[Dict[str, Any]] = []
            for line in res.stdout.splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 7:
                    instances.append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "top_hwnd": int(parts[2]),
                        "bind_hwnd": int(parts[3]),
                        "is_running": parts[4] == "1",
                        "pid": int(parts[5]),
                        "vbox_pid": int(parts[6]),
                    })
            return instances
        except Exception as err:
            _logger.error("Error listing LDPlayer instances: %s", err)
            return []


# Backward compatibility alias
InstanceLauncher = EmulatorController

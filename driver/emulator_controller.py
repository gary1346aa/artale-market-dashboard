"""LDPlayer emulator lifecycle controller.

Wraps ldconsole.exe commands to query, launch, reboot, or close Android
emulator instances programmatically, with COM sanitization,
process teardown sequencing, and modal dialog error handling.
"""

import logging
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import win32con
    import win32gui

    _HAS_WIN32: bool = True
except ImportError:
    _HAS_WIN32: bool = False

from config.settings import (
    DEFAULT_LDCONSOLE,
    DEVICE_INSTANCE_MAP,
    INSTANCE_DEVICE_MAP,
    INSTANCE_INDEX_MAP,
)

_logger = logging.getLogger(__name__)

# Windows power scheme GUIDs
_POWER_PLAN_GUIDS: Dict[str, str] = {
    "ultimate": "ee8b14d0-ad4d-4345-8f52-928a761433ff",
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
}

# COM & Process Synchronization Delays (seconds)
_COM_MUTEX_RELEASE_DELAY_SEC: float = 2.5
_TEARDOWN_GRACE_PERIOD_SEC: float = 3.0
_POST_TEARDOWN_COM_DELAY_SEC: float = 2.0
_DEFAULT_BOOT_TIMEOUT_SEC: int = 50
_ALL_BOOT_TIMEOUT_SEC: int = 60
_LAUNCH_DISPATCH_LOCK = threading.Lock()

# Modal error dialog keywords and recovery button texts
_ERROR_DIALOG_KEYWORDS: Tuple[str, ...] = ("COM", "無效", "重試", "載入失敗")
_ERROR_DIALOG_RECOVERY_LABELS: Tuple[str, ...] = ("嘗試修正", "修正", "確定")


def resolve_instance_index(instance_name: Union[str, int]) -> int:
    """Resolves an instance name, index string, or device ID to an LDPlayer numeric index.

    Args:
        instance_name: Instance name (e.g. '槍手'), numeric string ('3'), or device serial.

    Returns:
        int: LDPlayer numeric index, or -1 if unresolved.
    """
    key = str(instance_name).strip()
    if key in INSTANCE_INDEX_MAP:
        return INSTANCE_INDEX_MAP[key]
    if key in DEVICE_INSTANCE_MAP:
        return INSTANCE_INDEX_MAP.get(DEVICE_INSTANCE_MAP[key], -1)
    if key.isdigit():
        return int(key)
    return -1


def resolve_device_serial(instance_name: Union[str, int]) -> Optional[str]:
    """Resolves an instance identifier to its ADB device serial (e.g. 'emulator-5560').

    Args:
        instance_name: Instance name, index, or ADB device ID.

    Returns:
        Optional[str]: ADB device ID string if known, else None.
    """
    key = str(instance_name).strip()
    if key in INSTANCE_DEVICE_MAP:
        return INSTANCE_DEVICE_MAP[key]
    if key in DEVICE_INSTANCE_MAP:
        return key

    idx = resolve_instance_index(key)
    if idx >= 0:
        for name, i in INSTANCE_INDEX_MAP.items():
            if i == idx and name in INSTANCE_DEVICE_MAP:
                return INSTANCE_DEVICE_MAP[name]
    return None


class EmulatorController:
    """Manages LDPlayer instance lifecycle via ldconsole and OS process control.

    Attributes:
        ldconsole_path: Path to ldconsole.exe binary.
    """

    def __init__(
        self, ldconsole_path: Union[str, Path] = DEFAULT_LDCONSOLE
    ) -> None:
        """Initializes EmulatorController with ldconsole executable path.

        Args:
            ldconsole_path: File path to ldconsole.exe.
        """
        self.ldconsole_path = str(ldconsole_path)

    @staticmethod
    def _decode_output(raw_output: Union[bytes, str]) -> str:
        """Decodes raw CLI output across big5, cp950, utf-8, and system codepages.

        Args:
            raw_output: Raw bytes or string from subprocess stdout/stderr.

        Returns:
            str: Decoded text string.
        """
        if isinstance(raw_output, str):
            return raw_output
        for enc in ("utf-8", "cp950", "big5", "gbk"):
            try:
                return raw_output.decode(enc)
            except Exception:
                continue
        return raw_output.decode("latin1", errors="replace")

    def is_running(self, instance_name: str) -> bool:
        """Checks if an LDPlayer instance is currently running.

        Args:
            instance_name: Name, index, or ADB device ID of the instance.

        Returns:
            bool: True if instance is running, False otherwise.
        """
        # 1. Fast, reliable ADB device check
        dev_serial = resolve_device_serial(instance_name)
        if dev_serial:
            from driver.adb_driver import AdbDriver

            try:
                attached = AdbDriver.list_attached_devices()
                if dev_serial in attached:
                    return True
            except Exception:
                pass

        # 2. Fallback to ldconsole isrunning
        try:
            param = ["--index", str(instance_name)] if str(instance_name).isdigit() else ["--name", str(instance_name)]
            if str(instance_name).strip() in INSTANCE_INDEX_MAP:
                param = ["--index", str(INSTANCE_INDEX_MAP[str(instance_name).strip()])]
            res = subprocess.run(
                [self.ldconsole_path, "isrunning"] + param,
                capture_output=True,
                text=True,
                check=False,
            )
            out_str = self._decode_output(res.stdout).strip()
            return out_str == "running"
        except Exception as err:
            _logger.error(
                f"Error checking instance state for '{instance_name}': {err}"
            )
            return False

    @staticmethod
    def sanitize_com_service() -> None:
        """Flushes any orphaned Ld9BoxSVC.exe process before starting emulator instances.

        LDPlayer 9's virtualization engine relies on an out-of-process COM server
        (Ld9BoxSVC.exe). If an earlier batch was aborted or terminated abruptly,
        Ld9BoxSVC.exe may linger in memory with active mutexes. When a new dnplayer.exe
        starts, it tries to connect to this stale server, hangs, and pops up:
        '載入失敗 - 無效的COM接口，請重啟電腦後重試'.

        If no emulators (dnplayer.exe or Ld9BoxHeadless.exe) are actively running,
        this method forcefully terminates Ld9BoxSVC.exe and waits 2.5s for the Windows
        kernel to release VBoxSVC_Mutex and unregister COM interfaces.
        """
        try:
            cmd = (
                "Get-Process -Name dnplayer, Ld9BoxHeadless -ErrorAction SilentlyContinue | "
                "Measure-Object | Select-Object -ExpandProperty Count"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            count = int(res.stdout.strip() or 0)
            if count == 0:
                svc_cmd = (
                    "Get-Process -Name Ld9BoxSVC -ErrorAction SilentlyContinue | "
                    "Measure-Object | Select-Object -ExpandProperty Count"
                )
                svc_res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", svc_cmd],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                svc_count = int(svc_res.stdout.strip() or 0)
                if svc_count > 0:
                    _logger.warning(
                        f"Detected {svc_count} orphaned Ld9BoxSVC.exe process(es). Sanitizing COM state..."
                    )
                    subprocess.run(
                        ["taskkill", "/f", "/im", "Ld9BoxSVC.exe"],
                        capture_output=True,
                        check=False,
                    )
                    time.sleep(_COM_MUTEX_RELEASE_DELAY_SEC)
                    _logger.debug("COM state sanitized.")
        except Exception as err:
            _logger.debug(f"COM sanitization check error: {err}")

    @staticmethod
    def check_and_dismiss_error_dialogs() -> bool:
        """Finds and dismisses modal error dialogs like '載入失敗 - 無效的COM接口'.

        Returns:
            bool: True if an error dialog was detected and handled, False otherwise.
        """
        if not _HAS_WIN32:
            return False

        found = False

        def enum_window_cb(hwnd: int, _lparam: Any) -> bool:
            nonlocal found
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if "載入失敗" in title or cls == "#32770":
                    child_controls: List[Tuple[int, str]] = []

                    def child_cb(chwnd: int, _cparam: Any) -> bool:
                        child_controls.append((chwnd, win32gui.GetWindowText(chwnd)))
                        return True

                    try:
                        win32gui.EnumChildWindows(hwnd, child_cb, None)
                    except Exception:
                        pass

                    full_text = " ".join(t[1] for t in child_controls)
                    if any(k in full_text for k in _ERROR_DIALOG_KEYWORDS) or "載入失敗" in title:
                        _logger.warning(
                            f"Detected modal error dialog '{title}' [{cls}]: {full_text}"
                        )
                        # Attempt clicking recovery button first
                        clicked = False
                        for chwnd, ctext in child_controls:
                            if any(label in ctext for label in _ERROR_DIALOG_RECOVERY_LABELS):
                                _logger.info(
                                    f"Clicking recovery button '{ctext}' on dialog..."
                                )
                                win32gui.SendMessage(chwnd, win32con.BM_CLICK, 0, 0)
                                clicked = True
                                break
                        if not clicked:
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        found = True
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_window_cb, None)
        except Exception as err:
            _logger.debug(f"Error during dialog scan: {err}")

        return found

    def trigger_launch(self, instance_name: str) -> bool:
        """Dispatches the boot command for an LDPlayer instance without waiting for readiness.

        Args:
            instance_name: Name or index of the instance to boot.

        Returns:
            bool: True if launch was dispatched, False on error.
        """
        if self.is_running(instance_name):
            _logger.info(f"Instance '{instance_name}' is already running.")
            return True

        self.sanitize_com_service()
        _logger.info(f"Triggering boot for LDPlayer instance '{instance_name}'...")
        idx = resolve_instance_index(instance_name)

        try:
            with _LAUNCH_DISPATCH_LOCK:
                target_file = Path("data/launch_target.txt")
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(f"{idx}\n", encoding="utf-8")

                bat_path = Path("scripts/launch_emulators.bat").resolve()
                if bat_path.exists():
                    subprocess.Popen(["cmd.exe", "/c", str(bat_path)], shell=False)

                subprocess.run(
                    ["schtasks", "/run", "/tn", "LDLaunch"],
                    capture_output=True,
                    check=False,
                )
            return True
        except Exception as err:
            _logger.error(f"Launch trigger error for '{instance_name}': {err}")
            return False

    def wait_for_ready(
        self, instance_name: str, max_wait_sec: int = _DEFAULT_BOOT_TIMEOUT_SEC
    ) -> bool:
        """Polls until the instance is attached to ADB and stabilized.

        Args:
            instance_name: Name or index of the instance.
            max_wait_sec: Maximum seconds to wait.

        Returns:
            bool: True if instance is running and stabilized, False if timed out.
        """
        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            self.check_and_dismiss_error_dialogs()
            if self.is_running(instance_name):
                _logger.info(
                    f"Instance '{instance_name}' running. Waiting 15s for OS to settle..."
                )
                time.sleep(15)
                return True
            time.sleep(2)

        _logger.error(f"Timed out waiting for '{instance_name}' to boot.")
        return False

    def launch_instance(
        self, instance_name: str, max_wait_sec: int = _DEFAULT_BOOT_TIMEOUT_SEC
    ) -> bool:
        """Boots the instance visibly on the interactive desktop and waits for ADB attachment.

        Args:
            instance_name: Name or index of the instance to boot.
            max_wait_sec: Maximum seconds to wait for boot completion.

        Returns:
            bool: True if successfully booted, False if timed out.
        """
        if self.is_running(instance_name):
            _logger.info(f"Instance '{instance_name}' is already running.")
            return True

        if not self.trigger_launch(instance_name):
            return False
        return self.wait_for_ready(instance_name, max_wait_sec=max_wait_sec)

    def quit_instance(self, instance_name: str) -> bool:
        """Terminates an LDPlayer instance via elevated task bridge and CLI.

        Args:
            instance_name: Name, index, or device serial of the instance to quit.

        Returns:
            bool: True on successful command execution, False on error.
        """
        try:
            param = ["--index", str(instance_name)] if str(instance_name).isdigit() else ["--name", str(instance_name)]
            if str(instance_name).strip() in INSTANCE_INDEX_MAP:
                param = ["--index", str(INSTANCE_INDEX_MAP[str(instance_name).strip()])]

            # 1. Trigger elevated Task Scheduler bridge for real ldconsole execution
            if Path(self.ldconsole_path).name != "fake_ldconsole.exe":
                idx = resolve_instance_index(instance_name)
                with _LAUNCH_DISPATCH_LOCK:
                    target_file = Path("data/launch_target.txt")
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text(f"quit_{idx}", encoding="utf-8")
                    subprocess.run(
                        ["schtasks", "/run", "/tn", "LDLaunch"],
                        capture_output=True,
                        check=False,
                    )

            # 2. Direct CLI invocation
            subprocess.run(
                [self.ldconsole_path, "quit"] + param,
                capture_output=True,
                text=True,
                check=False,
            )
            return True
        except Exception as err:
            _logger.error(f"Error quitting instance '{instance_name}': {err}")
            return False

    def force_kill_instance(self, instance_name: str) -> None:
        """Force-kills specific dnplayer and Ld9BoxHeadless processes for a frozen instance.

        Args:
            instance_name: Name, index, or device serial of the frozen instance.
        """
        idx = resolve_instance_index(instance_name)
        try:
            cmd = (
                f"Get-CimInstance Win32_Process -Filter \"name = 'dnplayer.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*index={idx}*' }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, check=False)
            cmd_vbox = (
                f"Get-CimInstance Win32_Process -Filter \"name = 'Ld9BoxHeadless.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*leidian{idx}*' }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd_vbox], capture_output=True, check=False)
        except Exception as err:
            _logger.debug(f"Force kill error for instance {instance_name}: {err}")

    def quit_all(self) -> bool:
        """Terminates all running LDPlayer instances.

        Sequences graceful shutdown, process termination, and COM service teardown
        to avoid lingering mutex locks.

        Returns:
            bool: True if teardown commands completed, False on error.
        """
        try:
            target_file = Path("data/launch_target.txt")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("quit_all", encoding="utf-8")
            subprocess.run(
                ["schtasks", "/run", "/tn", "LDLaunch"],
                capture_output=True,
                check=False,
            )
            ld_dir = str(Path(self.ldconsole_path).parent)
            subprocess.run(
                [self.ldconsole_path, "quitall"],
                capture_output=True,
                cwd=ld_dir,
                check=False,
            )
            # 1. Allow guest OS and virtual disks to sync cleanly
            time.sleep(_TEARDOWN_GRACE_PERIOD_SEC)
            subprocess.run(["taskkill", "/f", "/im", "dnplayer.exe"], capture_output=True, check=False)
            subprocess.run(["taskkill", "/f", "/im", "Ld9BoxHeadless.exe"], capture_output=True, check=False)

            # 2. Terminate COM server and wait for kernel mutex to release
            subprocess.run(["taskkill", "/f", "/im", "Ld9BoxSVC.exe"], capture_output=True, check=False)
            time.sleep(_POST_TEARDOWN_COM_DELAY_SEC)
            return True
        except Exception as err:
            _logger.error(f"Error running quitall: {err}")
            return False

    def launch_all(
        self, max_wait_sec: int = _ALL_BOOT_TIMEOUT_SEC
    ) -> bool:
        """Cold-boots all 3 tracker instances (槍手, 打火機, 弩手) concurrently.

        Args:
            max_wait_sec: Maximum seconds to wait for all 3 instances to attach.

        Returns:
            bool: True if all 3 instances attached to ADB, False otherwise.
        """
        from driver.adb_driver import AdbDriver

        target_serials = ("emulator-5560", "emulator-5562", "emulator-5568")
        devs = AdbDriver.list_attached_devices()
        if all(d in devs for d in target_serials):
            _logger.info("All 3 tracker emulators are already running.")
            return True

        # Ensure COM server is not orphaned before launching all instances
        self.sanitize_com_service()

        _logger.info("Booting all 3 emulator instances...")
        try:
            target_file = Path("data/launch_target.txt")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("all\n", encoding="utf-8")

            # 1. Direct interactive session invocation
            bat_path = Path("scripts/launch_emulators.bat").resolve()
            if bat_path.exists():
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], shell=False)

            # 2. Elevated task bridge fallback
            subprocess.run(
                ["schtasks", "/run", "/tn", "LDLaunch"],
                capture_output=True,
                check=False,
            )
        except Exception as err:
            _logger.error(f"Error launching all instances: {err}")

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            self.check_and_dismiss_error_dialogs()
            devs = AdbDriver.list_attached_devices()
            if all(d in devs for d in target_serials):
                _logger.info("All 3 emulators attached to ADB. Waiting 10s for OS to stabilize...")
                time.sleep(10)
                return True
            time.sleep(3)

        _logger.warning("Timed out waiting for all 3 emulators to attach.")
        return False

    def list_instances(self) -> List[Dict[str, Any]]:
        """Lists all registered LDPlayer instances and their statuses.

        Returns:
            List[Dict[str, Any]]: List of dicts containing 'index', 'name',
            'top_hwnd', 'bind_hwnd', 'is_running', 'pid', 'vbox_pid'.
        """
        try:
            res = subprocess.run(
                [self.ldconsole_path, "list2"],
                capture_output=True,
                check=False,
            )
            out_str = self._decode_output(res.stdout)
            instances: List[Dict[str, Any]] = []
            for line in out_str.splitlines():
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
            _logger.error(f"Error listing LDPlayer instances: {err}")
            return []


def set_windows_power_plan(plan_name: str = "ultimate") -> bool:
    """Switches the active Windows power plan.

    Args:
        plan_name: Power plan alias ('ultimate' or 'balanced') or explicit GUID.

    Returns:
        bool: True if the power scheme was successfully activated, False otherwise.
    """
    guid = _POWER_PLAN_GUIDS.get(plan_name.lower(), plan_name)
    try:
        res = subprocess.run(
            ["powercfg", "/setactive", guid],
            capture_output=True,
            check=False,
        )
        return res.returncode == 0
    except Exception as err:
        _logger.debug(f"Error switching power plan to {plan_name}: {err}")
        return False


# Backward compatibility alias
InstanceLauncher = EmulatorController

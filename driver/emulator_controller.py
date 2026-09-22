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

    @staticmethod
    def _decode_output(raw_bytes: bytes) -> str:
        """Robustly decodes raw CLI output across big5, cp950, utf-8, and system codepages."""
        for enc in ("utf-8", "cp950", "big5", "gbk"):
            try:
                return raw_bytes.decode(enc)
            except Exception:
                continue
        return raw_bytes.decode("latin1", errors="replace")

    def is_running(self, instance_name: str) -> bool:
        """Checks if an LDPlayer instance is currently running.

        Args:
            instance_name: Name, index, or ADB device ID of the instance.

        Returns:
            True if instance is running, False otherwise.
        """
        # 1. Fast, 100% reliable ADB device check
        index_adb_map = {
            "槍手": "emulator-5560",
            "打火機": "emulator-5562",
            "弩手": "emulator-5568",
            "3": "emulator-5560",
            "4": "emulator-5562",
            "7": "emulator-5568",
            "emulator-5560": "emulator-5560",
            "emulator-5562": "emulator-5562",
            "emulator-5568": "emulator-5568",
        }
        dev_serial = index_adb_map.get(str(instance_name).strip())
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
            res = subprocess.run(
                [self.ldconsole_path, "isrunning"] + param,
                capture_output=True,
                check=False,
            )
            out_str = self._decode_output(res.stdout).strip()
            return out_str == "running"

        except Exception as err:
            _logger.error(
                "Error checking instance state for '%s': %s",
                instance_name,
                err,
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
                        "Detected %d orphaned Ld9BoxSVC.exe process(es). Sanitizing COM state...",
                        svc_count,
                    )
                    subprocess.run(
                        ["taskkill", "/f", "/im", "Ld9BoxSVC.exe"],
                        capture_output=True,
                        check=False,
                    )
                    time.sleep(2.5)  # Allow Windows kernel to release VBoxSVC_Mutex
                    _logger.info("COM state sanitized successfully.")
        except Exception as err:
            _logger.debug("COM sanitization check error: %s", err)

    @staticmethod
    def check_and_dismiss_error_dialogs() -> bool:
        """Finds and dismisses modal error dialogs like '載入失敗 - 無效的COM接口'.

        Returns True if a dialog was found and dismissed.
        """
        try:
            import win32gui
            import win32con
        except ImportError:
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
                    if any(k in full_text for k in ("COM", "無效", "重試", "載入失敗")) or "載入失敗" in title:
                        _logger.warning("Detected modal error dialog '%s' [%s]: %s", title, cls, full_text)
                        # Try clicking "嘗試修正" or "確定" button first
                        clicked = False
                        for chwnd, ctext in child_controls:
                            if any(btn_label in ctext for btn_label in ("嘗試修正", "修正", "確定")):
                                _logger.info("Clicking recovery button '%s' on dialog...", ctext)
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
            _logger.debug("Error during dialog scan: %s", err)

        return found

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

        # Ensure COM server is not orphaned before launching
        self.sanitize_com_service()

        _logger.info("Booting LDPlayer instance '%s' via automated launcher...", instance_name)
        index_map = {
            "槍手": 3,
            "打火機": 4,
            "弩手": 7,
            "emulator-5560": 3,
            "emulator-5562": 4,
            "emulator-5568": 7,
        }
        idx = index_map.get(instance_name, instance_name)

        # 1. Trigger via launch_target and direct ldconsole
        try:
            target_file = Path("data/launch_target.txt")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(f"{idx}\n", encoding="utf-8")
            
            # Direct batch execution
            bat_path = Path("scripts/launch_emulators.bat").resolve()
            if bat_path.exists():
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], shell=False)

            # Elevated Task Scheduler bridge
            subprocess.run(
                ["schtasks", "/run", "/tn", "LDLaunch"],
                capture_output=True,
                check=False,
            )
        except Exception as err:
            _logger.debug("Task scheduler trigger failed: %s", err)

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            self.check_and_dismiss_error_dialogs()
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
        """Terminates an LDPlayer instance via elevated task bridge.

        Args:
            instance_name: Name, index, or device serial of the instance to quit.

        Returns:
            True on successful command execution.
        """
        try:
            index_map = {
                "槍手": 3,
                "打火機": 4,
                "弩手": 7,
                "emulator-5560": 3,
                "emulator-5562": 4,
                "emulator-5568": 7,
            }
            idx = index_map.get(str(instance_name).strip(), instance_name)

            # 1. Trigger elevated Task Scheduler bridge
            target_file = Path("data/launch_target.txt")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(f"quit_{idx}", encoding="utf-8")
            subprocess.run(
                ["schtasks", "/run", "/tn", "LDLaunch"],
                capture_output=True,
                check=False,
            )

            # 2. Also direct CLI fallback
            param = ["--index", str(idx)] if str(idx).isdigit() else ["--name", str(idx)]
            ld_dir = str(Path(self.ldconsole_path).parent)
            subprocess.run(
                [self.ldconsole_path, "quit"] + param,
                capture_output=True,
                cwd=ld_dir,
                check=False,
            )
            return True
        except Exception as err:
            _logger.error("Error quitting instance '%s': %s", instance_name, err)
            return False

    def force_kill_instance(self, instance_name: str) -> None:
        """Force-kills specific dnplayer and Ld9BoxHeadless processes for a frozen instance."""
        index_map = {
            "槍手": 3,
            "打火機": 4,
            "弩手": 7,
            "emulator-5560": 3,
            "emulator-5562": 4,
            "emulator-5568": 7,
        }
        idx = index_map.get(str(instance_name).strip(), instance_name)
        try:
            cmd = f"Get-CimInstance Win32_Process -Filter \"name = 'dnplayer.exe'\" | Where-Object {{ $_.CommandLine -like '*index={idx}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, check=False)
            cmd_vbox = f"Get-CimInstance Win32_Process -Filter \"name = 'Ld9BoxHeadless.exe'\" | Where-Object {{ $_.CommandLine -like '*leidian{idx}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd_vbox], capture_output=True, check=False)
        except Exception as err:
            _logger.debug("Force kill error for instance %s: %s", instance_name, err)


    def quit_all(self) -> bool:
        """Terminates all running LDPlayer instances to preserve 0% idle power."""
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
            time.sleep(3.0)
            subprocess.run(["taskkill", "/f", "/im", "dnplayer.exe"], capture_output=True, check=False)
            subprocess.run(["taskkill", "/f", "/im", "Ld9BoxHeadless.exe"], capture_output=True, check=False)

            # 2. Terminate COM server and wait for kernel mutex to release
            subprocess.run(["taskkill", "/f", "/im", "Ld9BoxSVC.exe"], capture_output=True, check=False)
            time.sleep(2.0)
            return True
        except Exception as err:
            _logger.error("Error running quitall: %s", err)
            return False

    def launch_all(self, max_wait_sec: int = 60) -> bool:
        """Cold-boots all 3 tracker instances (槍手, 打火機, 弩手) concurrently."""
        from driver.adb_driver import AdbDriver
        devs = AdbDriver.list_attached_devices()
        if all(d in devs for d in ("emulator-5560", "emulator-5562", "emulator-5568")):
            _logger.info("All 3 tracker emulators are already running.")
            return True

        # Ensure COM server is not orphaned before launching all instances
        self.sanitize_com_service()

        _logger.info("Booting all 3 emulator instances via automated launcher...")
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
            _logger.error("Error launching all instances: %s", err)

        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            self.check_and_dismiss_error_dialogs()
            from driver.adb_driver import AdbDriver
            devs = AdbDriver.list_attached_devices()
            if all(d in devs for d in ("emulator-5560", "emulator-5562", "emulator-5568")):
                _logger.info("All 3 emulators attached to ADB. Waiting 10s for OS to stabilize...")
                time.sleep(10)
                return True
            time.sleep(3)

        _logger.warning("Timed out waiting for all 3 emulators to attach.")
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
            _logger.error("Error listing LDPlayer instances: %s", err)
            return []


def set_windows_power_plan(plan_name: str = "ultimate") -> bool:
    """Switches the active Windows power plan ('ultimate' or 'balanced')."""
    guid_map = {
        "ultimate": "ee8b14d0-ad4d-4345-8f52-928a761433ff",
        "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    }
    guid = guid_map.get(plan_name.lower(), plan_name)
    try:
        res = subprocess.run(["powercfg", "/setactive", guid], capture_output=True, check=False)
        return res.returncode == 0
    except Exception as err:
        _logger.debug("Error switching power plan to %s: %s", plan_name, err)
        return False


# Backward compatibility alias
InstanceLauncher = EmulatorController

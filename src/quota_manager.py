import json
import os
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional

QUOTA_FILE = Path(__file__).resolve().parent.parent / "data" / "quota_tracker.json"
DAILY_LIMIT = 500
RESET_HOUR = 8  # 08:00 AM
DEFAULT_INSTANCES = ["祈禱機", "槍手", "打火機", "弩手"]
_QUOTA_LOCK = threading.RLock()

class QuotaManager:
    """
    Tracks and enforces Artale 500-queries-per-day limit across multiple LDPlayer instances.
    Each account gets 500 searches per day, resetting at 08:00 AM daily.
    """
    def __init__(self, quota_file: Path = QUOTA_FILE, limit: int = DAILY_LIMIT, instances: Optional[List[str]] = None):
        self.quota_file = quota_file
        self.limit = limit
        self.known_instances = instances or DEFAULT_INSTANCES
        self._ensure_file()

    def _get_current_quota_day(self) -> str:
        now = datetime.now()
        # If before 08:00 AM, the quota cycle belongs to the previous calendar day
        if now.time() < time(RESET_HOUR, 0):
            quota_date = (now - timedelta(days=1)).date()
        else:
            quota_date = now.date()
        return quota_date.strftime("%Y-%m-%d")

    def _init_instances_dict(self) -> Dict:
        return {
            name: {
                "consumed_searches": 0,
                "remaining_searches": self.limit
            }
            for name in self.known_instances
        }

    def _ensure_file(self):
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.quota_file.exists():
            self._save({
                "quota_cycle_date": self._get_current_quota_day(),
                "active_instance": self.known_instances[0],
                "instances": self._init_instances_dict(),
                "last_updated": datetime.now().isoformat()
            })

    def _load(self) -> Dict:
        with _QUOTA_LOCK:
            curr_cycle = self._get_current_quota_day()
            try:
                with open(self.quota_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Check if quota cycle rolled over past 08:00 AM
                if data.get("quota_cycle_date") != curr_cycle:
                    data = {
                        "quota_cycle_date": curr_cycle,
                        "active_instance": self.known_instances[0],
                        "instances": self._init_instances_dict(),
                        "last_updated": datetime.now().isoformat()
                    }
                    self._save(data)
                    return data

                # Backwards compatibility migration if 'instances' is missing
                if "instances" not in data:
                    old_consumed = data.get("consumed_searches", 0)
                    old_remaining = data.get("remaining_searches", self.limit)
                    inst_dict = self._init_instances_dict()
                    inst_dict["祈禱機"]["consumed_searches"] = old_consumed
                    inst_dict["祈禱機"]["remaining_searches"] = old_remaining
                    data["instances"] = inst_dict
                    data["active_instance"] = self.known_instances[0]
                    self._save(data)

                # Ensure all known instances exist in data
                changed = False
                for name in self.known_instances:
                    if name not in data["instances"]:
                        data["instances"][name] = {
                            "consumed_searches": 0,
                            "remaining_searches": self.limit
                        }
                        changed = True

                if "active_instance" not in data or data["active_instance"] not in self.known_instances:
                    data["active_instance"] = self.known_instances[0]
                    changed = True

                if changed:
                    self._save(data)

                return data
            except Exception:
                fallback = {
                    "quota_cycle_date": curr_cycle,
                    "active_instance": self.known_instances[0],
                    "instances": self._init_instances_dict(),
                    "last_updated": datetime.now().isoformat()
                }
                self._save(fallback)
                return fallback

    def _save(self, data: Dict):
        with _QUOTA_LOCK:
            with open(self.quota_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def get_active_instance(self) -> str:
        data = self._load()
        return data.get("active_instance", self.known_instances[0])

    def switch_instance(self, instance_name: str):
        data = self._load()
        if instance_name in data.get("instances", {}):
            data["active_instance"] = instance_name
            data["last_updated"] = datetime.now().isoformat()
            self._save(data)

    def can_search(self, instance_name: Optional[str] = None, required: int = 1) -> bool:
        data = self._load()
        target = instance_name or data.get("active_instance", self.known_instances[0])
        inst_info = data.get("instances", {}).get(target, {})
        consumed = inst_info.get("consumed_searches", 0)
        return consumed + required <= self.limit

    def record_search(self, instance_name: Optional[str] = None, count: int = 1):
        data = self._load()
        target = instance_name or data.get("active_instance", self.known_instances[0])
        if target not in data.get("instances", {}):
            data["instances"][target] = {
                "consumed_searches": 0,
                "remaining_searches": self.limit
            }
        
        inst_info = data["instances"][target]
        inst_info["consumed_searches"] += count
        inst_info["remaining_searches"] = max(0, self.limit - inst_info["consumed_searches"])
        data["last_updated"] = datetime.now().isoformat()
        self._save(data)

    def get_available_instance(self, required: int = 1, allowed_instances: Optional[List[str]] = None) -> Optional[str]:
        """
        Returns the active instance if it has enough quota.
        Otherwise automatically switches and returns the next instance with available quota.
        Returns None if all instances are exhausted.
        """
        data = self._load()
        candidates = [k for k in self.known_instances if allowed_instances is None or k in allowed_instances]
        if not candidates:
            return None

        active = data.get("active_instance", candidates[0])
        
        # 1. If active instance is candidate and has enough quota, keep it
        if active in candidates and self.can_search(active, required=required):
            return active

        # 2. Rotate to the next instance that has enough quota
        for name in candidates:
            if self.can_search(name, required=required):
                self.switch_instance(name)
                return name

        # 3. All accounts exhausted for today
        return None

    def get_status(self, instance_name: Optional[str] = None) -> Dict:
        data = self._load()
        if instance_name:
            inst_info = data.get("instances", {}).get(instance_name, {})
            return {
                "quota_cycle_date": data.get("quota_cycle_date"),
                "instance": instance_name,
                "consumed_searches": inst_info.get("consumed_searches", 0),
                "remaining_searches": inst_info.get("remaining_searches", self.limit),
                "active": (instance_name == data.get("active_instance"))
            }
        # Overall status across all instances
        total_consumed = sum(v.get("consumed_searches", 0) for v in data.get("instances", {}).values())
        total_remaining = sum(v.get("remaining_searches", self.limit) for v in data.get("instances", {}).values())
        return {
            "quota_cycle_date": data.get("quota_cycle_date"),
            "active_instance": data.get("active_instance"),
            "total_consumed": total_consumed,
            "total_remaining": total_remaining,
            "total_capacity": len(data.get("instances", {})) * self.limit,
            "instances": data.get("instances", {})
        }

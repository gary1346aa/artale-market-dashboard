import os
import time
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image

logger = logging.getLogger("DatasetLogger")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "data" / "test_dataset"
MANIFEST_FILE = DATASET_DIR / "manifest.jsonl"
_MANIFEST_LOCK = threading.Lock()

def save_dataset_frame(
    frame: Optional[Image.Image],
    item_name: Optional[str],
    tab: str,
    page_num: int = 1,
    device_id: Optional[str] = None
) -> Optional[Path]:
    """
    Persists an uncompressed, raw captured frame to data/test_dataset/
    and records metadata into manifest.jsonl.
    """
    if frame is None:
        return None
    try:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        safe_item = "".join(c for c in (item_name or "unknown") if c.isalnum() or c in ("-", "_", "%"))
        dev_str = (device_id or "local").replace("-", "")
        filename = f"{ts}_{dev_str}_{tab}_{safe_item}_p{page_num}.png"
        filepath = DATASET_DIR / filename
        frame.save(filepath, format="PNG")

        manifest_record = {
            "file": filename,
            "path": str(filepath),
            "item_name": item_name,
            "tab": tab,
            "page_num": page_num,
            "device_id": device_id,
            "saved_at": datetime.now().isoformat()
        }
        with _MANIFEST_LOCK:
            with open(MANIFEST_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(manifest_record, ensure_ascii=False) + "\n")

        logger.debug(f"Saved dataset frame: {filename}")
        return filepath
    except Exception as e:
        logger.warning(f"Failed to save dataset frame: {e}")
        return None

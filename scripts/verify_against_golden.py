import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List
from PIL import Image

workspace_env = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
PROJECT_ROOT = Path(workspace_env) if workspace_env else Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recognition.digit_engine import parse_price_cell, parse_timestamp_cell
from recognition.table_parser import MarketParser

DATASET_DIR = PROJECT_ROOT / "data" / "test_dataset"
GOLDEN_PATH = PROJECT_ROOT / "data" / "golden_dataset.json"

def verify_against_golden(limit: int = 0):
    if not GOLDEN_PATH.exists():
        print(f"Error: Golden dataset not found at {GOLDEN_PATH}")
        sys.exit(1)

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden_data = json.load(f)

    records = golden_data.get("records", [])
    meta = golden_data.get("metadata", {})
    if limit > 0:
        records = records[:limit]
    print(f"=== Running Regression Verification Against Golden Dataset ===")
    print(f"Golden Standards: {len(records)} rows from {meta.get('total_images')} images (limit: {limit or 'all'})")

    t_start = time.time()
    
    # Stream opened image for adjacent rows in same image
    current_fn = None
    current_img = None
    
    total_checks = len(records)
    passed_checks = 0
    regressions = []

    for idx, rec in enumerate(records, 1):
        fn = rec["file"]
        if fn != current_fn:
            if current_img is not None:
                try:
                    current_img.close()
                except Exception:
                    pass
            img_path = DATASET_DIR / fn
            try:
                current_img = Image.open(img_path)
                current_fn = fn
            except Exception as e:
                regressions.append({"record": rec, "error": f"Failed to open image: {e}"})
                continue

        img = current_img
        parser = MarketParser(img)
        tab = rec["tab"]
        row_idx = rec["row_idx"]
        y1, y2 = parser.ROW_BOUNDS[row_idx]

        # 1. Total Price
        tot_crop = img.crop(parser._scale_box(687, y1, 844, y2))
        curr_tot = parse_price_cell(tot_crop, tab=tab)

        # 2. Unit Price
        unit_crop = img.crop(parser._scale_box(844, y1, 987, y2))
        curr_unit = parse_price_cell(unit_crop, tab=tab)
        if curr_unit is None and curr_tot is not None:
            curr_unit = curr_tot

        # 3. Timestamp
        curr_ts = None
        if tab == "market":
            meta_crop = img.crop(parser._scale_box(1027, y1 + 7, 1150, y1 + 41))
            curr_ts = parse_timestamp_cell(meta_crop)

        # Compare against golden
        is_pass = True
        failures = []

        if curr_tot != rec["golden_total_price"]:
            is_pass = False
            failures.append(f"Total Price mismatch: got {curr_tot}, expected {rec['golden_total_price']}")

        if curr_unit != rec["golden_unit_price"]:
            is_pass = False
            failures.append(f"Unit Price mismatch: got {curr_unit}, expected {rec['golden_unit_price']}")

        if tab == "market" and curr_ts != rec["golden_timestamp"]:
            is_pass = False
            failures.append(f"Timestamp mismatch: got '{curr_ts}', expected '{rec['golden_timestamp']}'")

        if is_pass:
            passed_checks += 1
        else:
            regressions.append({
                "file": fn,
                "row_idx": row_idx,
                "item_name": rec["item_name"],
                "failures": failures
            })

        if idx % 2000 == 0 or idx == total_checks:
            print(f"Verified {idx}/{total_checks} rows ({passed_checks} passing)...")

    duration = time.time() - t_start
    accuracy = (passed_checks / total_checks * 100) if total_checks else 100.0

    print("\n" + "=" * 60)
    print("        REGRESSION VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total Golden Rows Checked : {total_checks}")
    print(f"Passing Rows              : {passed_checks}/{total_checks} ({accuracy:.2f}%)")
    print(f"Regressions Found         : {len(regressions)}")
    print(f"Execution Duration        : {duration:.2f} seconds ({duration / total_checks * 1000:.2f} ms/row)")
    print("=" * 60)

    if regressions:
        print("\nREGRESSION DETAILS (First 10):")
        for r in regressions[:10]:
            print(f"  {r['file']} Row {r['row_idx']} ({r['item_name']}):")
            for f in r["failures"]:
                print(f"    - {f}")
        sys.exit(1)
    else:
        print("\nSUCCESS: All records matched the golden standard.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regression Verification Against Golden Dataset")
    parser.add_argument("--limit", type=int, default=0, help="Maximum records to verify (default: 0 for all)")
    args = parser.parse_args()
    verify_against_golden(limit=args.limit)


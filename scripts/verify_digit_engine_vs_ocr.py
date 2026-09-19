import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional
from PIL import Image

workspace_env = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
PROJECT_ROOT = Path(workspace_env) if workspace_env else Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recognition.digit_engine import parse_price_cell, parse_timestamp_cell
from recognition.table_parser import MarketParser
from recognition.text_ocr import extract_number, normalize_item_name, ocr_image
DATASET_DIR = PROJECT_ROOT / "data" / "test_dataset"
REPORT_PATH = PROJECT_ROOT / "data" / "digit_engine_vs_ocr_report.json"

def compare_image(img_path: Path) -> List[Dict[str, Any]]:
    try:
        img = Image.open(img_path)
    except Exception as e:
        print(f"Error opening image {img_path}: {e}")
        return []

    parser = MarketParser(img)
    tab = parser.detect_active_tab()
    results = []

    for row_idx, (y1, y2) in enumerate(parser.ROW_BOUNDS):
        # 1. Check if row is valid/occupied
        name_box = parser._scale_box(456, y1 + 5, 693, y2 - 5)
        name_crop = img.crop(name_box).resize((450, 70), Image.Resampling.LANCZOS)
        raw_name = ocr_image(name_crop, lang="zh-Hant-TW")
        item_name = normalize_item_name(raw_name)
        if not item_name or len(item_name) < 2:
            continue

        row_record = {
            "file": img_path.name,
            "tab": tab,
            "row_idx": row_idx,
            "item_name": item_name,
        }

        # 2. Total Price Cell
        tot_crop = img.crop(parser._scale_box(687, y1, 844, y2))
        t0 = time.perf_counter()
        de_tot = parse_price_cell(tot_crop, tab=tab)
        de_tot_time_ms = (time.perf_counter() - t0) * 1000

        tot_ocr_crop = img.crop(parser._scale_box(725, y1, 860, y1 + 32)).resize((350, 70), Image.Resampling.LANCZOS)
        t0 = time.perf_counter()
        raw_tot_ocr = ocr_image(tot_ocr_crop, lang="en-US") or ocr_image(tot_ocr_crop, lang="zh-Hant-TW")
        ocr_tot = extract_number(raw_tot_ocr)
        ocr_tot_time_ms = (time.perf_counter() - t0) * 1000

        row_record["total_price"] = {
            "digit_engine": de_tot,
            "ocr": ocr_tot,
            "ocr_raw": raw_tot_ocr,
            "match": (de_tot == ocr_tot),
            "de_time_ms": round(de_tot_time_ms, 3),
            "ocr_time_ms": round(ocr_tot_time_ms, 3)
        }

        # 3. Unit Price Cell
        unit_crop = img.crop(parser._scale_box(844, y1, 987, y2))
        t0 = time.perf_counter()
        de_unit = parse_price_cell(unit_crop, tab=tab)
        de_unit_time_ms = (time.perf_counter() - t0) * 1000

        unit_ocr_crop = img.crop(parser._scale_box(881, y1, 1006, y1 + 32)).resize((350, 70), Image.Resampling.LANCZOS)
        t0 = time.perf_counter()
        raw_unit_ocr = ocr_image(unit_ocr_crop, lang="en-US") or ocr_image(unit_ocr_crop, lang="zh-Hant-TW")
        ocr_unit = extract_number(raw_unit_ocr)
        ocr_unit_time_ms = (time.perf_counter() - t0) * 1000

        row_record["unit_price"] = {
            "digit_engine": de_unit,
            "ocr": ocr_unit,
            "ocr_raw": raw_unit_ocr,
            "match": (de_unit == ocr_unit),
            "de_time_ms": round(de_unit_time_ms, 3),
            "ocr_time_ms": round(ocr_unit_time_ms, 3)
        }

        # Divisibility checks
        if de_tot is not None and de_unit is not None and de_unit > 0:
            row_record["de_divisible"] = (de_tot % de_unit == 0)
        else:
            row_record["de_divisible"] = None

        if ocr_tot is not None and ocr_unit is not None and ocr_unit > 0:
            row_record["ocr_divisible"] = (ocr_tot % ocr_unit == 0)
        else:
            row_record["ocr_divisible"] = None

        # 4. Timestamp Cell (for market tab)
        if tab == "market":
            meta_crop = img.crop(parser._scale_box(1027, y1 + 7, 1150, y1 + 41))
            t0 = time.perf_counter()
            de_time = parse_timestamp_cell(meta_crop)
            de_time_ms = (time.perf_counter() - t0) * 1000

            meta_ocr_crop = meta_crop.resize((350, 75), Image.Resampling.LANCZOS)
            t0 = time.perf_counter()
            raw_meta_ocr = ocr_image(meta_ocr_crop, lang="en-US")
            ocr_time_ms = (time.perf_counter() - t0) * 1000

            time_match = re.search(
                r"(?P<year>202\d|2\d)\D+(?P<month>0?[1-9]|1[0-2])\D+(?P<day>0?[1-9]|[12]\d|3[01])\D+(?P<hour>[01]?\d|2[0-3])\D+(?P<minute>[0-5]\d)",
                raw_meta_ocr or ""
            )
            if time_match:
                d = time_match.groupdict()
                y = '20' + d['year'] if len(d['year']) == 2 else d['year']
                ocr_time = f"{y}-{int(d['month']):02d}-{int(d['day']):02d} {int(d['hour']):02d}:{int(d['minute']):02d}"
            else:
                ocr_time = None

            row_record["timestamp"] = {
                "digit_engine": de_time,
                "ocr": ocr_time,
                "ocr_raw": raw_meta_ocr,
                "match": (de_time == ocr_time),
                "de_time_ms": round(de_time_ms, 3),
                "ocr_time_ms": round(ocr_time_ms, 3)
            }

        results.append(row_record)

    return results

def run_verification(dataset_dir: Path = DATASET_DIR, limit: int = 20) -> Dict[str, Any]:
    images = sorted(dataset_dir.glob("*.png"))
    if limit > 0:
        images = images[:limit]
    print(f"=== Starting Digit Engine vs OCR Verification on {len(images)} images (limit: {limit or 'all'}) ===")

    all_rows: List[Dict[str, Any]] = []
    t_start = time.time()

    for idx, img_p in enumerate(images, 1):
        rows = compare_image(img_p)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(images):
            print(f"Processed {idx}/{len(images)} images ({len(all_rows)} total rows extracted)...")

    # Metric aggregations
    total_rows = len(all_rows)
    tot_price_matches = sum(1 for r in all_rows if r["total_price"]["match"])
    unit_price_matches = sum(1 for r in all_rows if r["unit_price"]["match"])
    
    timestamp_rows = [r for r in all_rows if "timestamp" in r]
    ts_matches = sum(1 for r in timestamp_rows if r["timestamp"]["match"])

    # Discrepancies
    discrepancies = []
    for r in all_rows:
        has_disc = False
        disc_details = {
            "file": r["file"],
            "item_name": r["item_name"],
            "tab": r["tab"],
            "row_idx": r["row_idx"],
        }
        if not r["total_price"]["match"]:
            has_disc = True
            disc_details["total_price"] = r["total_price"]
        if not r["unit_price"]["match"]:
            has_disc = True
            disc_details["unit_price"] = r["unit_price"]
        if "timestamp" in r and not r["timestamp"]["match"]:
            has_disc = True
            disc_details["timestamp"] = r["timestamp"]
        
        if has_disc:
            disc_details["de_divisible"] = r.get("de_divisible")
            disc_details["ocr_divisible"] = r.get("ocr_divisible")
            discrepancies.append(disc_details)

    # Average latencies
    de_tot_times = [r["total_price"]["de_time_ms"] for r in all_rows]
    ocr_tot_times = [r["total_price"]["ocr_time_ms"] for r in all_rows]
    de_unit_times = [r["unit_price"]["de_time_ms"] for r in all_rows]
    ocr_unit_times = [r["unit_price"]["ocr_time_ms"] for r in all_rows]

    avg_de_latency = (sum(de_tot_times) + sum(de_unit_times)) / (len(de_tot_times) + len(de_unit_times)) if de_tot_times else 0.0
    avg_ocr_latency = (sum(ocr_tot_times) + sum(ocr_unit_times)) / (len(ocr_tot_times) + len(ocr_unit_times)) if ocr_tot_times else 0.0

    summary = {
        "dataset_images_count": len(images),
        "total_extracted_rows": total_rows,
        "total_price_cells": {
            "total": total_rows,
            "matches": tot_price_matches,
            "discrepancies": total_rows - tot_price_matches,
            "agreement_rate": round(tot_price_matches / total_rows * 100, 2) if total_rows else 100.0
        },
        "unit_price_cells": {
            "total": total_rows,
            "matches": unit_price_matches,
            "discrepancies": total_rows - unit_price_matches,
            "agreement_rate": round(unit_price_matches / total_rows * 100, 2) if total_rows else 100.0
        },
        "timestamp_cells": {
            "total": len(timestamp_rows),
            "matches": ts_matches,
            "discrepancies": len(timestamp_rows) - ts_matches,
            "agreement_rate": round(ts_matches / len(timestamp_rows) * 100, 2) if timestamp_rows else 100.0
        },
        "latency_ms": {
            "digit_engine_avg_ms": round(avg_de_latency, 3),
            "ocr_avg_ms": round(avg_ocr_latency, 3),
            "speedup_factor": round(avg_ocr_latency / avg_de_latency, 1) if avg_de_latency > 0 else 0.0
        },
        "discrepancies_count": len(discrepancies),
        "discrepancies": discrepancies,
        "verification_duration_sec": round(time.time() - t_start, 2)
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("           VERIFICATION BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"Total Dataset Images  : {len(images)}")
    print(f"Total Table Rows      : {total_rows}")
    print(f"Total Price Agreement : {tot_price_matches}/{total_rows} ({summary['total_price_cells']['agreement_rate']}%)")
    print(f"Unit Price Agreement  : {unit_price_matches}/{total_rows} ({summary['unit_price_cells']['agreement_rate']}%)")
    if timestamp_rows:
        print(f"Timestamp Agreement   : {ts_matches}/{len(timestamp_rows)} ({summary['timestamp_cells']['agreement_rate']}%)")
    print(f"Digit Engine Latency  : {summary['latency_ms']['digit_engine_avg_ms']} ms/cell")
    print(f"WinOCR Latency        : {summary['latency_ms']['ocr_avg_ms']} ms/cell")
    print(f"Speedup Factor        : {summary['latency_ms']['speedup_factor']}x faster")
    print(f"Discrepancies Found   : {len(discrepancies)}")
    print(f"Full Report Saved to  : {REPORT_PATH}")
    print("=" * 60 + "\n")

    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digit Engine vs OCR Verification")
    parser.add_argument("--limit", type=int, default=20, help="Max images to verify (default: 20, 0 for all)")
    args = parser.parse_args()
    run_verification(limit=args.limit)


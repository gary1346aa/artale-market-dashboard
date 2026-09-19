import sys
import os
import re
import time
import json
from pathlib import Path
from PIL import Image
import winocr

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

workspace_env = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
PROJECT_ROOT = Path(workspace_env) if workspace_env else Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recognition.digit_engine import parse_quota_header

def ocr_header(frame):
    try:
        w, h = frame.size
        sx, sy = w / 1280.0, h / 720.0
        crop = frame.crop((int(475 * sx), int(10 * sy), int(815 * sx), int(60 * sy)))
        cw, ch = crop.size
        scaled = crop.resize((cw * 2, ch * 2), Image.Resampling.LANCZOS)
        res = winocr.recognize_pil_sync(scaled, lang="zh-Hant-TW")
        text = res.get("text", "").strip()
        m = re.search(r"(\d{1,3})\s*/\s*500", text)
        if m:
            return int(m.group(1)), text
        m2 = re.search(r"(\d{1,3})\s*[/|lI]\s*5\d*", text)
        if m2:
            return int(m2.group(1)), text
        return None, text
    except Exception as e:
        return None, str(e)

def main():
    dataset = PROJECT_ROOT / "data" / "test_dataset"
    pngs = sorted(list(dataset.glob("*.png")))
    total_imgs = len(pngs)
    if not total_imgs:
        print("No test images found in data/test_dataset/")
        return

    sample_count = 50
    step = max(1, total_imgs // sample_count)
    sampled = pngs[::step][:sample_count]

    print(f"Testing {len(sampled)} real Auction House screencaps (Dataset total: {total_imgs})...\n")

    matches = 0
    discrepancies = []
    de_times = []
    ocr_times = []
    de_success_count = 0
    ocr_success_count = 0

    for idx, p in enumerate(sampled, 1):
        img = Image.open(p)

        t0 = time.perf_counter()
        de_res = parse_quota_header(img)
        de_time = (time.perf_counter() - t0) * 1000
        de_times.append(de_time)
        de_val = de_res[0] if de_res else None
        if de_val is not None:
            de_success_count += 1

        t0 = time.perf_counter()
        ocr_val, ocr_raw = ocr_header(img)
        ocr_time = (time.perf_counter() - t0) * 1000
        ocr_times.append(ocr_time)
        if ocr_val is not None:
            ocr_success_count += 1

        is_match = (de_val == ocr_val)
        if is_match:
            matches += 1
        else:
            discrepancies.append({
                "file": p.name,
                "de": de_val,
                "ocr": ocr_val,
                "ocr_raw": ocr_raw
            })

        status = "MATCH" if is_match else "DISCREPANCY"
        short_name = p.name[:45]
        print(f"[{idx:02d}/{len(sampled)}] {short_name:<45} | DE: {str(de_val):<4} ({de_time:.1f}ms) | OCR: {str(ocr_val):<4} ({ocr_time:.1f}ms) -> {status}")

    print("\n" + "=" * 75)
    print(f"COMPARISON REPORT (Digit Engine vs WinOCR on {len(sampled)} Real Images):")
    print(f"  Exact Agreement : {matches}/{len(sampled)} ({matches/len(sampled)*100:.1f}%)")
    print(f"  DE Valid Header : {de_success_count}/{len(sampled)} ({de_success_count/len(sampled)*100:.1f}%)")
    print(f"  OCR Valid Header: {ocr_success_count}/{len(sampled)} ({ocr_success_count/len(sampled)*100:.1f}%)")
    print(f"  Avg Latency     : Digit Engine {sum(de_times)/len(de_times):.2f}ms vs WinOCR {sum(ocr_times)/len(ocr_times):.2f}ms")
    print("=" * 75)

    if discrepancies:
        print(f"\nDiscrepancies ({len(discrepancies)}):")
        for d in discrepancies:
            print(f"  - {d['file']}:")
            print(f"      Digit Engine : {d['de']}")
            print(f"      WinOCR       : {d['ocr']} (raw OCR text: {repr(d['ocr_raw'])})")

if __name__ == "__main__":
    main()

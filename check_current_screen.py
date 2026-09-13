import os
import sys
import time
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

from src.window_manager import WindowManager

OUTPUT_RESULT = Path(r"C:\Users\gary1\screen_check_result.txt")
IMAGE_OUT = Path(r"C:\Users\gary1\.gemini\antigravity-cli\brain\c86b3e83-edcf-492c-a4b9-3f5c42ff639b\current_screen_now.png")
TPL_PATH = Path(r"C:\Users\gary1\artale_market_tracker\assets\free_market_indicator.png")

def evaluate_screen(frame: Image.Image) -> dict:
    w, h = frame.size
    report = {
        "width": w,
        "height": h,
        "is_auction": False,
        "is_free_market": False,
        "is_home_screen": False,
        "details": []
    }

    # 1. Check Auction House
    try:
        top_p = frame.getpixel((640, 50))[:3]
        top_ok = abs(top_p[0] - top_p[1]) <= 5 and abs(top_p[1] - top_p[2]) <= 5 and 40 <= top_p[0] <= 60

        hdr_p = frame.getpixel((955, 155))[:3]
        hdr_ok = abs(hdr_p[0] - hdr_p[1]) <= 5 and abs(hdr_p[1] - hdr_p[2]) <= 5 and 25 <= hdr_p[0] <= 45

        t1 = frame.getpixel((244, 90))[:3]
        t2 = frame.getpixel((320, 90))[:3]
        tab_ok = (t1[1] > 100 and t1[2] > 100) or (t2[1] > 100 and t2[2] > 100)

        if top_ok and hdr_ok and tab_ok:
            report["is_auction"] = True
            report["details"].append("Auction House landmarks detected (top modal, table header, cyan tab).")
    except Exception as e:
        report["details"].append(f"Auction check error: {e}")

    # 2. Check Free Market (自由市場)
    try:
        fm_score = None
        if TPL_PATH.exists():
            tpl = Image.open(TPL_PATH).convert("RGB")
            crop = frame.crop((50, 50, 140, 75)).convert("RGB")
            diff = ImageChops.difference(crop, tpl)
            fm_score = sum(ImageStat.Stat(diff).mean)
            report["details"].append(f"Free Market name template diff score: {fm_score:.2f} (threshold < 40.0)")
            if fm_score < 40.0:
                report["is_free_market"] = True

        # Secondary check: HP/MP bar at (600, 647) and (600, 668)
        p_hp = frame.getpixel((600, 647))[:3]
        p_mp = frame.getpixel((600, 668))[:3]
        hp_ok = (p_hp[0] > 180 and p_hp[1] < 160 and p_hp[2] < 160)
        mp_ok = (p_mp[2] > 180 and p_mp[0] < 100 and p_mp[1] > 80)
        if hp_ok and mp_ok:
            report["details"].append("MapleStory in-game HP/MP status HUD detected.")
            # If template score was somewhat close or not available, HUD reinforces Free Market
            if fm_score is not None and fm_score < 70.0:
                report["is_free_market"] = True
    except Exception as e:
        report["details"].append(f"Free market check error: {e}")

    # 3. Check Home Screen (LDPlayer Android Desktop)
    try:
        # Dark wallpaper check across middle
        p_mid1 = frame.getpixel((640, 400))[:3]
        p_mid2 = frame.getpixel((640, 500))[:3]
        dark_bg = (max(p_mid1) < 45) and (max(p_mid2) < 45)

        # Android status bar at top right (1240, 25)
        p_stat = frame.getpixel((1240, 25))[:3]
        stat_bar = (p_stat[0] > 180 and p_stat[1] > 180 and p_stat[2] > 180) or (max(p_stat) < 60)

        # Search bar at top center (640, 70)
        p_search = frame.getpixel((640, 70))[:3]
        search_dark = max(p_search) < 55

        if dark_bg and not report["is_auction"] and not report["is_free_market"]:
            report["is_home_screen"] = True
            report["details"].append("Android Desktop / Home Screen detected (dark launcher wallpaper, no game HUD).")
    except Exception as e:
        report["details"].append(f"Home screen check error: {e}")

    return report

def main():
    lines = []
    lines.append(f"=== Screen Inspection at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    instances_to_check = ["祈禱機", "槍手", "LDPlayer", "雷電"]
    found_any = False

    for target in instances_to_check:
        win_mgr = WindowManager(title_keywords=[target])
        hwnd = win_mgr.find_window()
        if not hwnd:
            continue

        found_any = True
        lines.append(f"\nTarget instance: '{target}' (HWND: {hwnd})")
        win_mgr.bring_to_front()
        time.sleep(0.5)

        frame = win_mgr.capture_frame()
        if not frame:
            lines.append("Failed to capture frame!")
            continue

        # Save frame
        frame.save(IMAGE_OUT)
        lines.append(f"Captured frame saved to: {IMAGE_OUT} (Size: {frame.size})")

        eval_res = evaluate_screen(frame)
        lines.append(f"Screen Evaluation:")
        lines.append(f"  - Is Auction House: {eval_res['is_auction']}")
        lines.append(f"  - Is Free Market:   {eval_res['is_free_market']}")
        lines.append(f"  - Is Home Screen:   {eval_res['is_home_screen']}")
        for d in eval_res["details"]:
            lines.append(f"    * {d}")

        if eval_res["is_auction"]:
            lines.append("DIAGNOSIS: The screen is currently inside the AUCTION HOUSE (拍賣場).")
        elif eval_res["is_free_market"]:
            lines.append("DIAGNOSIS: The screen is currently inside the FREE MARKET (自由市場). ALT+7 is SAFE to use.")
        elif eval_res["is_home_screen"]:
            lines.append("DIAGNOSIS: The screen is currently on the HOME SCREEN (雷電桌面/主畫面). DO NOT USE ALT+7! MUST USE ALT+9.")
        else:
            lines.append("DIAGNOSIS: The screen is in another state (e.g. Loading, Login, or Character Select). DO NOT USE ALT+7! MUST USE ALT+9.")
        break

    if not found_any:
        lines.append("No active LDPlayer window found matching target instances.")

    output_text = "\n".join(lines)
    print(output_text)
    OUTPUT_RESULT.write_text(output_text, encoding="utf-8")

if __name__ == "__main__":
    main()

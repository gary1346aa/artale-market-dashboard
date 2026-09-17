import re
from typing import Optional, Dict, Any
from PIL import Image, ImageOps
import winocr

def preprocess_for_ocr(img: Image.Image, scale: float = 2.5, binarize: bool = True, threshold: int = 130) -> Image.Image:
    """
    Upscales and optionally binarizes pixel text against dark backgrounds.
    """
    w, h = img.size
    scaled = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    if binarize:
        gray = ImageOps.grayscale(scaled)
        return gray.point(lambda p: 255 if p > threshold else 0)
    return scaled

def ocr_image(img: Image.Image, lang: str = "zh-Hant-TW") -> str:
    """
    Executes Windows Media OCR on a PIL image.
    """
    result = winocr.recognize_pil_sync(img, lang=lang)
    return result.get("text", "").strip()

def extract_number(text: str) -> Optional[int]:
    """
    Extracts the primary integer value from a string with possible punctuation.
    E.g. '85,555 (8萬 5,555)' -> 85555
         '4 , 395 , 000' -> 4395000
         '1,112,111,111 II Ifg 1,211Æ 1,111)' -> 1112111111
         '(439Æ 5,000)' -> 4395000
         '(870萬)' -> 8700000
    """
    if not text or not text.strip():
        return None

    MAX_CEILING = 30_000_000_000

    # Replace common OCR misreads of digits
    trans = str.maketrans({
        "O": "0", "o": "0", "D": "0",
        "S": "5", "s": "5",
        "l": "1", "I": "1",
        "B": "8",
        "Z": "2", "z": "2"
    })
    cleaned = text.translate(trans).strip()

    # Split into lines (primary price is strictly on line 1)
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if not lines:
        return None

    line1 = lines[0]

    # If any opening parenthesis or Chinese unit exists, cut it off
    for sep in ["(", "（", "[", "【", "億", "亿", "萬", "万"]:
        if sep in line1:
            line1 = line1.split(sep)[0].strip()

    # Ignore all punctuation (dots, commas, spaces, dashes, symbols) and extract pure digits
    digits = re.sub(r"[^\d]", "", line1)
    if digits:
        try:
            val = int(digits)
            if 0 < val <= MAX_CEILING:
                return val
        except ValueError:
            pass

    return None

import difflib
import json
from pathlib import Path

_WATCHLIST_CACHE = None

def get_canonical_watchlist() -> list:
    global _WATCHLIST_CACHE
    if _WATCHLIST_CACHE is None:
        wl_path = Path(__file__).resolve().parent.parent / "items_watchlist.json"
        if wl_path.exists():
            try:
                with open(wl_path, "r", encoding="utf-8") as f:
                    raw_wl = json.load(f)
                    _WATCHLIST_CACHE = list(raw_wl.keys()) if isinstance(raw_wl, dict) else raw_wl
            except Exception:
                _WATCHLIST_CACHE = []
        else:
            _WATCHLIST_CACHE = []
    return _WATCHLIST_CACHE

def normalize_item_name(text: str) -> str:
    """
    Cleans up common OCR artifacts on pixel fonts and matches against canonical watchlist items.
    """
    if not text:
        return ""
    # Filter out UI / error message text captured as items
    if any(err in text for err in ["失敗", "取消", "確定", "搜尋", "求失"]):
        return ""

    cleaned = text.replace(" ", "")
    # Strip leading non-alphanumeric / non-Chinese symbols (e.g. ':', '|', '.', '-')
    cleaned = re.sub(r"^[^a-zA-Z0-9\u4e00-\u9fff]+", "", cleaned)
    # Remove leading noise digits if present (e.g. icon count overlay)
    cleaned = re.sub(r"^\d+", "", cleaned)
    # Normalize percent signs and brackets
    cleaned = cleaned.replace("℅", "%").replace("c/o", "%")
    cleaned = cleaned.replace("]", "").replace("【", "").replace("】", "")
    
    # Common OCR typo dictionary
    TYPO_MAP = {
        '結加特器': '凍結加持器',
        '慧母': '智慧母礦',
        '碎片': '時間碎片',
        '問片': '時間碎片',
        '時片': '時間碎片',
        '高移石': '高級瞬移之石',
        '背包': '神祕背包',
        '蠖身符': '護身符',
        '天花': '漫天花雨',
        '夭花雨': '漫天花雨',
        '谩夭花': '漫天花雨',
        '〕É釁30': '挑釁 30',
        '頭防禦卷軸70%': '頭盔防禦卷軸70%',
        '漫天花雨箱(11%': '漫天花雨箱(11個)',
        '蓮水晶': '幸運水晶',
        '幸蓮水品': '幸運水晶',
        '幸永品': '幸運水晶',
        '力量永品': '力量水晶',
        '壢水品': '力量水晶',
        '慧水品': '智慧水晶',
        '運水品': '幸運水晶',
        '捷水品': '敏捷水晶',
    }
    if cleaned in TYPO_MAP:
        return TYPO_MAP[cleaned]

    # Common OCR radical and character misrecognitions
    cleaned = cleaned.replace("防卷", "防禦卷")
    cleaned = cleaned.replace("頸", "頭").replace("頝", "頭").replace("皕", "頭")
    cleaned = cleaned.replace("墜鉓", "墜飾").replace("峷", "幸").replace("装", "裝")
    cleaned = cleaned.replace("奬", "獎").replace("獎劻", "獎勵")
    cleaned = cleaned.replace("漫夭", "漫天")
    cleaned = cleaned.replace("丿凍結", "凍結").replace("巧高級", "高級")

    # Standardize '卷' to '卷軸' if missing '軸'
    cleaned = re.sub(r"卷(?!軸)", "卷軸", cleaned)

    # Standardize missing or trailing percent signs on scrolls only
    if "卷" in cleaned:
        cleaned = re.sub(r"(10|30|60|70|100)$", r"\1%", cleaned)
        cleaned = re.sub(r"([0-9]+)[^0-9%]+$", r"\1%", cleaned)

    # Strip [技能書] prefix if present in OCR
    cleaned = re.sub(r"^\[?技能書\]?", "", cleaned)

    # Standardize '盔' prefix to '頭盔'
    if cleaned.startswith("盔") and not cleaned.startswith("頭盔"):
        cleaned = "頭" + cleaned

    if "炎魔" in cleaned and "殘" in cleaned and "頭盔" not in cleaned:
        cleaned = "殘暴炎魔頭盔"

    # Normalize 飄雪結晶
    if any(k in cleaned for k in ["飄雪", "雪結", "飄結", "結品"]) and "凍結" not in cleaned:
        cleaned = "飄雪結晶"
    elif cleaned in ["結晶", "結品"]:
        cleaned = "飄雪結晶"

    # Match against canonical watchlist
    watchlist = get_canonical_watchlist()
    if cleaned in watchlist:
        return cleaned

    # Direct match ignoring whitespace (e.g. '楓葉祝福 20' <-> '楓葉祝福20')
    for w in watchlist:
        if w.replace(" ", "") == cleaned:
            return w

    # Fuzzy match against watchlist (>70% match)
    best_match, best_score = None, 0
    for w in watchlist:
        score = difflib.SequenceMatcher(None, cleaned, w.replace(" ", "")).ratio()
        if score > best_score:
            best_score, best_match = score, w

    if best_score >= 0.70:
        return best_match

    # Discard known noise words
    if cleaned in ["啟結", "夭花", "結加持器", "花雨"] or len(cleaned) < 2:
        return ""

    return cleaned

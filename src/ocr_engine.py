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
    """
    if not text or not text.strip():
        return None
    # Strip everything starting from '('
    cleaned = text.split("(")[0].strip()
    # Replace common OCR misreads of digits
    trans = str.maketrans({
        "S": "5", "s": "5",
        "O": "0", "o": "0",
        "l": "1", "I": "1",
        "B": "8",
        "Z": "2", "z": "2"
    })
    cleaned = cleaned.translate(trans)
    tokens = cleaned.split()
    if not tokens:
        return None
    digits_only = re.sub(r"[^\d]", "", tokens[0])
    if digits_only:
        try:
            return int(digits_only)
        except ValueError:
            return None
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
                    _WATCHLIST_CACHE = json.load(f)
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
    
    # Common OCR radical and character misrecognitions
    cleaned = cleaned.replace("防卷", "防禦卷")
    cleaned = cleaned.replace("頸", "頭").replace("頝", "頭").replace("皕", "頭")
    cleaned = cleaned.replace("墜鉓", "墜飾").replace("峷", "幸").replace("装", "裝")
    cleaned = cleaned.replace("奬", "獎").replace("獎劻", "獎勵")
    cleaned = cleaned.replace("漫夭", "漫天")
    cleaned = cleaned.replace("丿凍結", "凍結").replace("巧高級", "高級")

    # Standardize '卷' to '卷軸' if missing '軸'
    cleaned = re.sub(r"卷(?!軸)", "卷軸", cleaned)

    # Standardize missing or trailing percent signs on scrolls
    cleaned = re.sub(r"(10|30|60|70|100)$", r"\1%", cleaned)
    cleaned = re.sub(r"([0-9]+)[^0-9%]+$", r"\1%", cleaned)

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

    # Fuzzy match against watchlist (>70% match)
    best_match, best_score = None, 0
    for w in watchlist:
        score = difflib.SequenceMatcher(None, cleaned, w).ratio()
        if score > best_score:
            best_score, best_match = score, w

    if best_score >= 0.70:
        return best_match

    # Discard known noise words
    if cleaned in ["啟結", "夭花", "結加持器", "花雨"] or len(cleaned) < 2:
        return ""

    return cleaned

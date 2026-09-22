"""Windows Media OCR integration and item name normalization.

Provides image pre-processing, wrapper for Windows Media OCR (WinOCR),
heuristic numeric cleaners, and typo correction rules for in-game item names.
"""

import difflib
import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional

from PIL import Image, ImageOps
import winocr

from config.settings import WATCHLIST_PATH

_logger = logging.getLogger(__name__)

MAX_PRICE_CEILING = 30_000_000_000

DIGIT_TRANSLATION_TABLE = str.maketrans({
    "O": "0", "o": "0", "D": "0",
    "S": "5", "s": "5",
    "l": "1", "I": "1",
    "B": "8",
    "Z": "2", "z": "2",
})

OCR_TYPO_MAP: Dict[str, str] = {
    "結加特器": "凍結加持器",
    "慧母": "智慧母礦",
    "碎片": "時間碎片",
    "問片": "時間碎片",
    "時片": "時間碎片",
    "高移石": "高級瞬移之石",
    "背包": "神祕背包",
    "蠖身符": "護身符",
    "天花": "漫天花雨",
    "夭花雨": "漫天花雨",
    "谩夭花": "漫天花雨",
    "〕É釁30": "挑釁 30",
    "頭防禦卷軸70%": "頭盔防禦卷軸70%",
    "漫天花雨箱(11%": "漫天花雨箱(11個)",
    "蓮水晶": "幸運水晶",
    "幸蓮水品": "幸運水晶",
    "幸永品": "幸運水晶",
    "力量永品": "力量水晶",
    "壢水品": "敏捷水晶",
    "壢水晶": "敏捷水晶",
    "壢水": "敏捷水晶",
    "慧水品": "智慧水晶",
    "運水品": "幸運水晶",
    "捷水品": "敏捷水晶",
}

_WATCHLIST_CACHE: Optional[List[str]] = None


def preprocess_for_ocr(
    img: Image.Image,
    scale: float = 2.5,
    binarize: bool = True,
    threshold: int = 130,
) -> Image.Image:
    """Upscales and optionally binarizes pixel text against dark backgrounds.

    Args:
        img: Input PIL Image.
        scale: Upscaling multiplier.
        binarize: Whether to convert to black & white thresholded image.
        threshold: Grayscale cutoff threshold (0..255).

    Returns:
        Processed PIL Image ready for OCR recognition.
    """
    w, h = img.size
    scaled = img.resize(
        (int(w * scale), int(h * scale)), Image.Resampling.LANCZOS
    )
    if binarize:
        gray = ImageOps.grayscale(scaled)
        return gray.point(lambda p: 255 if p > threshold else 0)
    return scaled


def ocr_image(img: Image.Image, lang: str = "zh-Hant-TW") -> str:
    """Executes Windows Media OCR on a PIL image.

    Args:
        img: PIL Image to recognize.
        lang: OCR language code (default 'zh-Hant-TW').

    Returns:
        Extracted text string stripped of whitespace.
    """
    result = winocr.recognize_pil_sync(img, lang=lang)
    return result.get("text", "").strip()


def extract_number(text: str) -> Optional[int]:
    """Extracts integer value from OCR text with punctuation or misread digits.

    Args:
        text: Raw OCR string (e.g. '85,555 (8萬 5,555)').

    Returns:
        Parsed integer, or None if no valid digits were found.
    """
    if not text or not text.strip():
        return None

    cleaned = text.translate(DIGIT_TRANSLATION_TABLE).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return None

    line1 = lines[0]
    for sep in ("(", "（", "[", "【", "億", "亿", "萬", "万"):
        if sep in line1:
            line1 = line1.split(sep)[0].strip()

    digits = re.sub(r"[^\d]", "", line1)
    if digits:
        try:
            val = int(digits)
            if 0 < val <= MAX_PRICE_CEILING:
                return val
        except ValueError:
            pass

    return None


def get_canonical_watchlist(
    watchlist_path: Optional[Path] = None,
) -> List[str]:
    """Retrieves cached or newly loaded list of canonical watchlist item names.

    Args:
        watchlist_path: Optional custom path to items_watchlist.json.

    Returns:
        List of canonical item names.
    """
    global _WATCHLIST_CACHE
    if _WATCHLIST_CACHE is None:
        path = watchlist_path or WATCHLIST_PATH
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    _WATCHLIST_CACHE = (
                        list(raw.keys()) if isinstance(raw, dict) else raw
                    )
            except Exception as err:
                _logger.warning(f"Failed to load watchlist for OCR: {err}")
                _WATCHLIST_CACHE = []
        else:
            _WATCHLIST_CACHE = []
    return _WATCHLIST_CACHE


def normalize_item_name(
    text: str, watchlist_path: Optional[Path] = None
) -> str:
    """Cleans up common OCR artifacts on pixel fonts and matches against watchlist.

    Args:
        text: Raw OCR text string of the item name cell.
        watchlist_path: Optional path to items_watchlist.json.

    Returns:
        Clean canonical item name string, or empty string if noise/error text.
    """
    if not text:
        return ""

    if any(err in text for err in ("失敗", "取消", "確定", "搜尋", "求失")):
        return ""

    cleaned = text.replace(" ", "")
    cleaned = re.sub(r"^[^a-zA-Z0-9\u4e00-\u9fff]+", "", cleaned)
    cleaned = re.sub(r"^\d+", "", cleaned)
    cleaned = cleaned.replace("℅", "%").replace("c/o", "%")
    cleaned = cleaned.replace("]", "").replace("【", "").replace("】", "")

    if cleaned in OCR_TYPO_MAP:
        return OCR_TYPO_MAP[cleaned]

    cleaned = cleaned.replace("壢", "敏捷")
    cleaned = cleaned.replace("防卷", "防禦卷")
    cleaned = cleaned.replace("頸", "頭").replace("頝", "頭").replace("皕", "頭")
    cleaned = (
        cleaned.replace("墜鉓", "墜飾")
        .replace("峷", "幸")
        .replace("装", "裝")
    )
    cleaned = cleaned.replace("奬", "獎").replace("獎劻", "獎勵")
    cleaned = cleaned.replace("漫夭", "漫天")
    cleaned = cleaned.replace("丿凍結", "凍結").replace("巧高級", "高級")

    # Standardize '卷' to '卷軸' if missing '軸'
    cleaned = re.sub(r"卷(?!軸)", "卷軸", cleaned)

    # Standardize missing or trailing percent signs on scrolls
    if "卷" in cleaned:
        cleaned = re.sub(r"(10|30|60|70|100)$", r"\1%", cleaned)
        cleaned = re.sub(r"([0-9]+)[^0-9%]+$", r"\1%", cleaned)

    cleaned = re.sub(r"^\[?技能書\]?", "", cleaned)

    if cleaned.startswith("盔") and not cleaned.startswith("頭盔"):
        cleaned = "頭" + cleaned

    if "炎魔" in cleaned and "殘" in cleaned and "頭盔" not in cleaned:
        cleaned = "殘暴炎魔頭盔"

    if any(k in cleaned for k in ("飄雪", "雪結", "飄結", "結品")) and "凍結" not in cleaned:
        cleaned = "飄雪結晶"
    elif cleaned in ("結晶", "結品"):
        cleaned = "飄雪結晶"

    watchlist = get_canonical_watchlist(watchlist_path)
    if cleaned in watchlist:
        return cleaned

    # Match ignoring whitespace
    for w in watchlist:
        if w.replace(" ", "") == cleaned:
            return w

    # Fuzzy match (>70%)
    best_match: Optional[str] = None
    best_score: float = 0.0
    for w in watchlist:
        score = difflib.SequenceMatcher(
            None, cleaned, w.replace(" ", "")
        ).ratio()
        if score > best_score:
            best_score = score
            best_match = w

    if best_score >= 0.70 and best_match:
        return best_match

    if cleaned in ("啟結", "夭花", "結加持器", "花雨") or len(cleaned) < 2:
        return ""

    return cleaned

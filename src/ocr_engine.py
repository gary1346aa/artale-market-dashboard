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

def normalize_item_name(text: str) -> str:
    """
    Cleans up common OCR artifacts on pixel fonts (e.g. '卷】0%' -> '卷軸10%', '℅' -> '%').
    """
    cleaned = text.replace(" ", "")
    # Remove leading noise digits if present
    cleaned = re.sub(r"^\d+", "", cleaned)
    # Normalize percent signs
    cleaned = cleaned.replace("℅", "%").replace("c/o", "%")
    # Common OCR misreads in MapleStory pixel font
    cleaned = cleaned.replace("卷】", "卷軸")
    cleaned = cleaned.replace("卷]0%", "卷軸10%")
    cleaned = cleaned.replace("卷】0%", "卷軸10%")
    cleaned = cleaned.replace("卷怕10%", "卷軸10%")
    cleaned = cleaned.replace("防卷", "防禦卷")
    cleaned = cleaned.replace("頸", "頭")
    cleaned = cleaned.replace("頝", "頭")
    cleaned = cleaned.replace("皕", "頭")

    # Standardize '卷' to '卷軸' if missing '軸'
    cleaned = re.sub(r"卷(?!軸)", "卷軸", cleaned)

    # Standardize '盔' prefix to '頭盔'
    if cleaned.startswith("盔") and not cleaned.startswith("頭盔"):
        cleaned = "頭" + cleaned

    if "炎魔" in cleaned and "殘" in cleaned and "頭盔" not in cleaned:
        cleaned = "殘暴炎魔頭盔"
    return cleaned

"""Domain logic for item categorization and metadata extraction.

Provides canonical categorization for market items and scroll rate parsing
used across the web dashboard, chart visualization, and search indexing.
"""

from typing import Dict, List

# Standard market categories used in UI filters and database reporting
CATEGORY_ACCESSORY_SCROLL = "飾品卷"
CATEGORY_WEAPON_SCROLL = "武器卷"
CATEGORY_ARMOR_SCROLL = "防具卷"
CATEGORY_CASH = "現金道具"
CATEGORY_MATERIAL = "材料"
CATEGORY_SKILL_BOOK = "技能書"
CATEGORY_CONSUMABLE = "消耗"
CATEGORY_OTHER = "其他"

ALL_CATEGORIES: List[str] = [
    CATEGORY_ACCESSORY_SCROLL,
    CATEGORY_WEAPON_SCROLL,
    CATEGORY_ARMOR_SCROLL,
    CATEGORY_CASH,
    CATEGORY_MATERIAL,
    CATEGORY_SKILL_BOOK,
    CATEGORY_CONSUMABLE,
    CATEGORY_OTHER,
]

# Badge display titles used in high-resolution candlestick charts
CATEGORY_BADGES: Dict[str, str] = {
    CATEGORY_ACCESSORY_SCROLL: "飾品卷軸",
    CATEGORY_WEAPON_SCROLL: "武器卷軸",
    CATEGORY_ARMOR_SCROLL: "防具卷軸",
    CATEGORY_CASH: "商城道具",
    CATEGORY_MATERIAL: "鍛造材料",
    CATEGORY_SKILL_BOOK: "技能書",
    CATEGORY_CONSUMABLE: "消耗道具",
    CATEGORY_OTHER: "市場道具",
}

_CONSUMABLE_KEYWORDS = ("超級藥水", "特殊藥水", "藥水")
_SKILL_KEYWORDS = ("楓葉祝福", "挑釁", "技能書", "母書")
_CASH_KEYWORDS = (
    "喇叭", "瞬移", "突襲", "背包", "護身符", "初始化",
    "加持器", "漫天花雨", "飄雪結晶"
)
_ACCESSORY_KEYWORDS = ("墜飾", "眼部裝飾", "臉部裝飾", "眼部", "臉部", "耳環", "戒指", "腰帶")
_WEAPON_KEYWORDS = (
    "拳套", "弓", "弩", "單手劍", "雙手劍", "矛", "槍", "短劍",
    "手套攻擊力", "手套攻擊", "指虎", "火槍", "短杖", "長杖"
)
_ARMOR_KEYWORDS = ("頭盔", "鞋子", "手套")
_MATERIAL_KEYWORDS = ("時間碎片", "碎片", "母礦", "水晶")
_SCROLL_RATES = ("100%", "70%", "60%", "30%", "10%")


def classify_item(name: str) -> str:
    """Classifies an in-game item into a canonical category.

    Args:
        name: In-game item name.

    Returns:
        Canonical category string (e.g., '飾品卷', '消耗', '材料').
    """
    if any(keyword in name for keyword in _CONSUMABLE_KEYWORDS):
        return CATEGORY_CONSUMABLE
    if any(keyword in name for keyword in _SKILL_KEYWORDS):
        return CATEGORY_SKILL_BOOK
    if any(keyword in name for keyword in _CASH_KEYWORDS):
        return CATEGORY_CASH
    if any(keyword in name for keyword in _ACCESSORY_KEYWORDS):
        return CATEGORY_ACCESSORY_SCROLL
    if any(keyword in name for keyword in _WEAPON_KEYWORDS):
        return CATEGORY_WEAPON_SCROLL
    if any(keyword in name for keyword in _ARMOR_KEYWORDS):
        return CATEGORY_ARMOR_SCROLL
    if any(keyword in name for keyword in _MATERIAL_KEYWORDS):
        return CATEGORY_MATERIAL
    return CATEGORY_OTHER


def classify_item_type(name: str) -> str:
    """Classifies an item into its badge display name for charts.

    Maintains backwards compatibility with earlier kline_plotter logic.

    Args:
        name: In-game item name.

    Returns:
        Formatted badge title (e.g., '飾品卷軸', '鍛造材料').
    """
    cat = classify_item(name)
    return CATEGORY_BADGES.get(cat, "市場道具")


def get_scroll_rate(name: str) -> str:
    """Extracts the scroll percentage rate from an item name.

    Args:
        name: In-game item name.

    Returns:
        Extracted percentage string (e.g. '60%', '10%') or '-' if not a rated scroll.
    """
    for rate in _SCROLL_RATES:
        if rate in name:
            return rate
    return "-"

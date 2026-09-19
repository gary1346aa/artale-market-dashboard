"""Unit tests for item categorization and scroll rate extraction."""

import unittest

from core.categories import (
    CATEGORY_ACCESSORY_SCROLL,
    CATEGORY_ARMOR_SCROLL,
    CATEGORY_CASH,
    CATEGORY_CONSUMABLE,
    CATEGORY_MATERIAL,
    CATEGORY_SKILL_BOOK,
    CATEGORY_WEAPON_SCROLL,
    classify_item,
    classify_item_type,
    get_scroll_rate,
)


class TestItemCategories(unittest.TestCase):
    """Tests for item categorization rules."""

    def test_consumables_classification(self):
        """Classify common potion and consumable items."""
        self.assertEqual(classify_item("超級藥水"), CATEGORY_CONSUMABLE)
        self.assertEqual(classify_item("特殊藥水"), CATEGORY_CONSUMABLE)

    def test_scrolls_classification(self):
        """Classify weapon, armor, and accessory upgrade scrolls."""
        self.assertEqual(classify_item("槍攻擊卷軸60%"), CATEGORY_WEAPON_SCROLL)
        self.assertEqual(classify_item("手套攻擊卷軸10%"), CATEGORY_WEAPON_SCROLL)
        self.assertEqual(classify_item("頭盔智力卷軸100%"), CATEGORY_ARMOR_SCROLL)
        self.assertEqual(classify_item("鞋子敏捷卷軸60%"), CATEGORY_ARMOR_SCROLL)
        self.assertEqual(classify_item("墜飾力量卷軸30%"), CATEGORY_ACCESSORY_SCROLL)
        self.assertEqual(classify_item("眼部裝飾敏捷卷軸10%"), CATEGORY_ACCESSORY_SCROLL)
        self.assertEqual(classify_item("耳環智力卷軸60%"), CATEGORY_ACCESSORY_SCROLL)

    def test_materials_and_skillbooks(self):
        """Classify crafting materials, cash items, and mastery skillbooks."""
        self.assertEqual(classify_item("時間碎片"), CATEGORY_MATERIAL)
        self.assertEqual(classify_item("力量母礦"), CATEGORY_MATERIAL)
        self.assertEqual(classify_item("力量水晶"), CATEGORY_MATERIAL)
        self.assertEqual(classify_item("飄雪結晶"), CATEGORY_CASH)
        self.assertEqual(classify_item("楓葉祝福 20"), CATEGORY_SKILL_BOOK)
        self.assertEqual(classify_item("楓葉祝福 30"), CATEGORY_SKILL_BOOK)

    def test_scroll_rate_parsing(self):
        """Extract exact success rate percentage from scroll item names."""
        self.assertEqual(get_scroll_rate("手套攻擊卷軸60%"), "60%")
        self.assertEqual(get_scroll_rate("墜飾力量卷軸30%"), "30%")
        self.assertEqual(get_scroll_rate("眼部裝飾智力卷軸10%"), "10%")
        self.assertEqual(get_scroll_rate("頭盔體力卷軸100%"), "100%")
        self.assertEqual(get_scroll_rate("頭盔防禦卷軸70%"), "70%")
        self.assertEqual(get_scroll_rate("力量水晶"), "-")
        self.assertEqual(get_scroll_rate("超級藥水"), "-")

    def test_badge_classification_cjk(self):
        """Verify CJK badge tags for dashboard and chart rendering."""
        self.assertEqual(classify_item_type("槍攻擊卷軸60%"), "武器卷軸")
        self.assertEqual(classify_item_type("頭盔智力卷軸100%"), "防具卷軸")
        self.assertEqual(classify_item_type("墜飾敏捷卷軸30%"), "飾品卷軸")
        self.assertEqual(classify_item_type("時間碎片"), "鍛造材料")
        self.assertEqual(classify_item_type("超級藥水"), "消耗道具")
        self.assertEqual(classify_item_type("楓葉祝福 20"), "技能書")


if __name__ == "__main__":
    unittest.main()

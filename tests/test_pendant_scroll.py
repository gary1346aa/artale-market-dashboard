import sys
import io
import sqlite3
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser import MarketParser
from src.ocr_engine import normalize_item_name
from src.database import init_db, save_active_listings, save_matched_trades, DB_PATH
from src.models import ActiveListing, MatchedTrade

def test_pendant_scroll():
    print("==================================================")
    print("TESTING ITEM: 墜飾幸運卷軸30%")
    print("==================================================")

    # 1. Test OCR Text Normalization
    print("\n[Step 1: Normalization Test]")
    test_cases = [
        ("墜 飾 幸 運 卷 軸 30 %", "墜飾幸運卷軸30%"),
        ("墜飾幸運卷30%", "墜飾幸運卷軸30%"),
        (":墜飾幸運卷】30%", "墜飾幸運卷軸30%"),
        ("1墜飾幸運卷]30%", "墜飾幸運卷軸30%"),
        ("墜飾幸運卷30℅", "墜飾幸運卷軸30%"),
    ]
    for raw, expected in test_cases:
        norm = normalize_item_name(raw)
        assert norm == expected, f"Expected {expected}, got {norm}"
        print(f"  [PASS] '{raw}' -> '{norm}'")

    # 2. Test Image OCR Extraction with Realistic Image
    print("\n[Step 2: Realistic Image Parsing Test]")
    base_img_path = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789197683302.png")
    test_img = Image.open(base_img_path).copy()
    draw = ImageDraw.Draw(test_img)

    # Clear Row 1 cells and draw '墜飾幸運卷軸30%'
    bg_color = (42, 42, 42)
    draw.rectangle([(335, 155), (555, 201)], fill=bg_color)
    draw.rectangle([(550, 155), (820, 201)], fill=bg_color)

    font = ImageFont.truetype("msjh.ttc", 16)
    draw.text((365, 160), "墜飾幸運卷軸30%", fill=(255, 255, 255), font=font)
    draw.text((580, 160), "880,000", fill=(255, 255, 255), font=font)
    draw.text((710, 160), "880,000", fill=(255, 255, 255), font=font)

    parser = MarketParser(test_img)
    listings = parser.parse_active_listings()
    row1 = listings[0]

    print(f"  Parsed Listing from Image:")
    print(f"    - Item Name : {row1.item_name}")
    print(f"    - Unit Price: {row1.unit_price:,}")
    print(f"    - Total     : {row1.total_price:,}")
    print(f"    - Quantity  : {row1.quantity}")

    assert row1.item_name == "墜飾幸運卷軸30%", f"Expected '墜飾幸運卷軸30%', got '{row1.item_name}'"
    assert row1.unit_price == 880000, f"Expected 880,000, got {row1.unit_price}"
    assert row1.quantity == 1, f"Expected 1, got {row1.quantity}"
    print("  [PASS] Image OCR extracted exact fields.")

    # 3. Test Database Persistence & Arbitrage / Spread Analytics
    print("\n[Step 3: Database & Spread Analytics Test]")
    init_db()
    # Use dedicated test DB to prevent interference with production market.db
    TEST_DB = Path(__file__).resolve().parent.parent / "data" / "test_pendant.db"
    if TEST_DB.exists():
        TEST_DB.unlink()
    import src.database
    src.database.DB_PATH = TEST_DB
    init_db()

    save_active_listings([row1])

    # Save matched trade: 950,000
    matched_sample = MatchedTrade(
        item_name="墜飾幸運卷軸30%",
        quantity=2,
        matched_unit_price=950000,
        total_matched_price=1900000,
        trade_time="2026-09-12 15:10"
    )
    save_matched_trades([matched_sample])

    # Query Spread
    with sqlite3.connect(TEST_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.item_name,
                MIN(a.unit_price) as lowest_ask,
                m.matched_unit_price as recent_match,
                ROUND(((MIN(a.unit_price) - m.matched_unit_price) * 100.0 / m.matched_unit_price), 2) as spread_pct
            FROM active_listings a
            JOIN matched_trades m ON a.item_name = m.item_name
            WHERE a.item_name = '墜飾幸運卷軸30%'
            GROUP BY a.item_name
        """)
        item_name, lowest_ask, recent_match, spread = cursor.fetchone()
        
        print(f"  Analytics Results for '{item_name}':")
        print(f"    - Active Lowest Ask : {lowest_ask:,}")
        print(f"    - Recent Match Price: {recent_match:,}")
        print(f"    - Spread Difference : {spread}%")

        if spread < 0:
            print(f"    - Valuation Signal  : 🚨 UNDERVALUED (Listing is {abs(spread)}% cheaper than actual trades)")
        else:
            print(f"    - Valuation Signal  : OVERVALUED")

        assert spread == -7.37, f"Expected spread -7.37%, got {spread}%"
        print("  [PASS] Spread analytics matched expected financial metrics.")

    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except PermissionError:
            pass

    print("\n==================================================")
    print("TEST COMPLETED SUCCESSFULLY: 墜飾幸運卷軸30% ALL PASS")
    print("==================================================")

if __name__ == "__main__":
    test_pendant_scroll()

import sys
import io
from pathlib import Path
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser import MarketParser
from src.database import init_db, save_active_listings, save_matched_trades

def test_image(image_path: Path):
    print(f"\n==========================================")
    print(f"Testing: {image_path.name}")
    print(f"==========================================")
    
    if not image_path.exists():
        print(f"File not found: {image_path}")
        return

    img = Image.open(image_path)
    parser = MarketParser(img)
    result = parser.parse()

    print(f"Active Tab Detected: [{result['tab'].upper()}]")
    if result["pagination"]:
        print(f"Pagination: Page {result['pagination'][0]} of {result['pagination'][1]}")
    
    print(f"\nExtracted Records ({len(result['records'])} items):")
    for idx, r in enumerate(result["records"], 1):
        if result["tab"] == "market":
            print(f"  [{idx}] {r.item_name} | Qty: {r.quantity} | Matched Unit: {r.matched_unit_price:,} | Total: {r.total_matched_price:,} | Trade Time: {r.trade_time}")
        else:
            print(f"  [{idx}] {r.item_name} | Qty: {r.quantity} | Unit: {r.unit_price:,} | Total: {r.total_price:,} | Time: {r.remaining_time}")

    # Persist to database
    init_db()
    if result["tab"] == "market":
        save_matched_trades(result["records"])
        print(f"-> Saved {len(result['records'])} matched trades into SQLite (table: matched_trades).")
    else:
        save_active_listings(result["records"])
        print(f"-> Saved {len(result['records'])} active listings into SQLite (table: active_listings).")

def main():
    img_sell = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789197683302.png")
    img_match = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789199276346.png")

    test_image(img_sell)
    test_image(img_match)

if __name__ == "__main__":
    main()

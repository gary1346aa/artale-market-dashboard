import sys
import io
from pathlib import Path
from PIL import Image

# Ensure stdout handles UTF-8 cleanly on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser import MarketParser
from src.database import init_db, save_active_listings

def main():
    sample_img_path = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789197683302.png")
    if not sample_img_path.exists():
        print(f"Error: Sample image not found at {sample_img_path}")
        return

    print("Loading image...")
    img = Image.open(sample_img_path)
    parser = MarketParser(img)

    quota = parser.parse_search_quota()
    print(f"Search Quota: {quota.current_used}/{quota.max_limit}" if quota else "Search Quota: Not detected")

    pagination = parser.parse_pagination()
    print(f"Pagination: Page {pagination[0]} of {pagination[1]}" if pagination else "Pagination: Not detected")

    print("\nParsing Active Listings (查詢):")
    listings = parser.parse_active_listings()
    for idx, item in enumerate(listings, 1):
        print(f"[{idx}] {item.item_name} | Qty: {item.quantity} | Total: {item.total_price:,} | Unit: {item.unit_price:,} | Time: {item.remaining_time} | Seller: {item.seller_id}")

    # Test saving to database
    init_db()
    save_active_listings(listings)
    print(f"\nSuccessfully stored {len(listings)} listings into SQLite database.")

if __name__ == "__main__":
    main()

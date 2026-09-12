import sys
import io
import sqlite3
from pathlib import Path
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.window_manager import WindowManager
from src.parser import MarketParser
from src.collector import MarketCollector
from src.database import init_db, save_active_listings, save_matched_trades, DB_PATH

class MockWindowManager(WindowManager):
    """
    Simulates WindowManager by serving real game screenshots.
    Allows automated end-to-end testing without needing live game interaction.
    """
    def __init__(self, sample_images):
        super().__init__()
        self.sample_images = sample_images
        self.current_idx = 0
        self.clicked_coords = []

    def find_window(self):
        return 12345  # Simulated HWND

    def get_window_rect(self):
        # Simulate 1024 x 576 window located at (100, 100)
        return {"left": 100, "top": 100, "width": 1024, "height": 576}

    def bring_to_front(self):
        return True

    def capture_frame(self):
        if not self.sample_images:
            return None
        img_path = self.sample_images[self.current_idx % len(self.sample_images)]
        return Image.open(img_path)

    def to_screen_coords(self, ref_x: int, ref_y: int):
        # Maps ref coordinates into simulated screen space (left=100, top=100)
        return (100 + ref_x, 100 + ref_y)


def run_tests():
    print("==================================================")
    print("1. RUNNING UNIT & RESOLUTION SCALING TESTS")
    print("==================================================")
    
    mock_mgr = MockWindowManager([])
    # Test coordinate mapping for 1024x576 at (100, 100)
    screen_pt = mock_mgr.to_screen_coords(272, 46)
    assert screen_pt == (372, 146), f"Expected (372, 146), got {screen_pt}"
    print("  [PASS] Coordinate mapping verified.")

    # Test scaling to 1920x1080
    class HighResMock(WindowManager):
        def get_window_rect(self):
            return {"left": 0, "top": 0, "width": 1920, "height": 1080}
    highres_mgr = HighResMock()
    hr_pt = highres_mgr.to_screen_coords(1024, 576)
    assert hr_pt == (1920, 1080), f"Expected (1920, 1080), got {hr_pt}"
    print("  [PASS] 1080p dynamic DPI scaling verified.")

    print("\n==================================================")
    print("2. RUNNING END-TO-END COLLECTOR SIMULATION")
    print("==================================================")
    
    sample1 = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789197683302.png")
    sample2 = Path("C:/Users/gary1/.gemini/antigravity-cli/brain/c86b3e83-edcf-492c-a4b9-3f5c42ff639b/.user_uploaded/media_1789199276346.png")

    assert sample1.exists() and sample2.exists(), "Sample screenshots must exist"

    # Reset test database for clean verification
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM active_listings")
        conn.execute("DELETE FROM matched_trades")
        conn.commit()

    # Create collector with simulated window manager
    mock_sim = MockWindowManager([sample1, sample2])
    collector = MarketCollector(window_mgr=mock_sim)

    # Frame 1: Query tab (Sell Asks)
    mock_sim.current_idx = 0
    res1 = collector.scrape_current_page()
    print(f"  Frame 1 detected tab: [{res1['tab']}] | Extracted: {res1['count']} listings")
    assert res1["tab"] == "query", f"Expected 'query', got {res1['tab']}"
    assert res1["count"] == 7, f"Expected 7 listings, got {res1['count']}"

    # Frame 2: Market tab (Matched Trades)
    mock_sim.current_idx = 1
    res2 = collector.scrape_current_page()
    print(f"  Frame 2 detected tab: [{res2['tab']}] | Extracted: {res2['count']} trades")
    assert res2["tab"] == "market", f"Expected 'market', got {res2['tab']}"
    assert res2["count"] == 7, f"Expected 7 trades, got {res2['count']}"

    print("\n==================================================")
    print("3. VERIFYING DATABASE PERSISTENCE & ANALYTICS")
    print("==================================================")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Check active_listings
        cursor.execute("SELECT count(*), min(unit_price), max(unit_price), sum(total_price) FROM active_listings")
        active_cnt, min_p, max_p, sum_p = cursor.fetchone()
        print(f"  [Active Listings Table]:")
        print(f"    - Total records: {active_cnt}")
        print(f"    - Lowest ask unit price: {min_p:,}")
        print(f"    - Highest ask unit price: {max_p:,}")
        print(f"    - Total order book depth: {sum_p:,}")
        assert active_cnt == 7

        # Check matched_trades
        cursor.execute("SELECT count(*), min(matched_unit_price), max(matched_unit_price), sum(total_matched_price) FROM matched_trades")
        trade_cnt, min_t, max_t, sum_t = cursor.fetchone()
        print(f"\n  [Matched Trades Table]:")
        print(f"    - Total records: {trade_cnt}")
        print(f"    - Lowest matched trade: {min_t:,}")
        print(f"    - Highest matched trade: {max_t:,}")
        print(f"    - Total traded volume: {sum_t:,}")
        assert trade_cnt == 7

        # Insert a simulated matched trade for '頭盔防禦卷軸10%' to verify cross-market spread analytics
        cursor.execute("""
            INSERT INTO matched_trades (item_name, quantity, matched_unit_price, total_matched_price, trade_time)
            VALUES ('頭盔防禦卷軸10%', 1, 88000, 88000, '2026-09-12 15:30')
        """)
        conn.commit()

        # Test cross-table spread query (Items present in both tables)
        cursor.execute("""
            SELECT 
                a.item_name,
                MIN(a.unit_price) as lowest_ask,
                m.matched_unit_price as recent_trade,
                ROUND(((MIN(a.unit_price) - m.matched_unit_price) * 100.0 / m.matched_unit_price), 2) as spread_pct
            FROM active_listings a
            JOIN matched_trades m ON a.item_name = m.item_name
            GROUP BY a.item_name
        """)
        spreads = cursor.fetchall()
        print(f"\n  [Cross-Market Spread Analysis (Ask vs Matched Trade)]:")
        for name, ask, trade, spread in spreads:
            status = "🚨 UNDERVALUED / SNIPE" if spread < 0 else "NORMAL / PREMIUM"
            print(f"    * {name}: Lowest Ask={ask:,} | Recent Trade={trade:,} | Spread={spread}% ({status})")
        assert len(spreads) > 0, "Spread query should return at least one matched item"

    print("\n==================================================")
    print("ALL TESTS COMPLETED SUCCESSFULLY! ALL PASS.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()

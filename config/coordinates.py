"""Standard UI coordinates and bounding box specifications for Artale.

Provides canonical 1280x720 pixel coordinate anchors and bounding boxes for
all interactive elements, table cells, buttons, and visual landmarks.
"""

from typing import List, NamedTuple, Tuple


class Point(NamedTuple):
    """Represents an integer 2D screen coordinate (x, y)."""
    x: int
    y: int


class Rect(NamedTuple):
    """Represents an axis-aligned bounding box (x1, y1, x2, y2)."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)


# ==============================================================================
# Interactive Click Targets (Canonical 1280x720 Canvas)
# ==============================================================================
POS_QUICK_SEARCH = Point(x=280, y=40)
POS_CONFIRM_INPUT = Point(x=1185, y=685)  # [確定] Button
POS_QUERY_TAB = Point(x=244, y=90)        # [查詢] Tab (Active Listings)
POS_MARKET_TAB = Point(x=522, y=90)       # [市價] Tab (Matched Trades)
POS_SIDEBAR_SEARCH = Point(x=279, y=327)
POS_START_SEARCH = Point(x=312, y=553)
POS_PRICE_HEADER = Point(x=945, y=170)    # [每個價錢] Column Header for sorting
POS_NEXT_PAGE = Point(x=850, y=140)       # [>] Next Page Button
POS_FIRST_PAGE = Point(x=666, y=140)      # [|<] First Page Button

# Navigation & Free Market Anchors
POS_MENU_BUTTON = Point(x=1171, y=116)
POS_AUCTION_BUTTON = Point(x=1239, y=616)
POS_LEAVE_AUCTION = Point(x=1015, y=45)   # [離開] Button in top-right
POS_CONFIRM_EXIT = Point(x=635, y=615)
POS_STOP_DIALOG = Point(x=349, y=461)
POS_FREE_MARKET_MENU_BUTTON = Point(x=1140, y=445)  # [自由市場] in mobile menu

# Game Bootstrap & Launcher Anchors
POS_HOME_MSW_ICON = Point(x=640, y=210)             # MapleStory Worlds on home screen
POS_MSW_SEARCH_BUTTON = Point(x=411, y=69)          # Magnifier in MSW lobby top bar
POS_MSW_SEARCH_INPUT = Point(x=350, y=56)           # Search text field
POS_MSW_PLAY_BUTTON = Point(x=473, y=1143)          # [▶ 遊玩] on Artale details page
POS_LOGIN_BUTTON = Point(x=980, y=472)              # [登入] on title screen
POS_SELECT_CHARACTER_BUTTON = Point(x=847, y=275)   # [選擇角色] on character select platform
POS_DISMISS_DRAWER = Point(x=500, y=360)            # Tap outside drawer to close mobile menu
POS_EXIT_MODAL_CANCEL = Point(x=483, y=490)         # [否] button on "前往大廳" exit dialog

# ==============================================================================
# Precision OCR & Digit Extraction Regions (Canonical 1280x720)
# ==============================================================================
# Remaining search quota digits 'XXX' (left-aligned directly before the slash)
REGION_QUOTA_DIGITS = Rect(x1=543, y1=10, x2=574, y2=28)

# Pagination indicator candidate boxes (e.g. '1 / 20')
PAGINATION_BOXES = [
    Rect(x1=710, y1=110, x2=860, y2=155),
    Rect(x1=720, y1=115, x2=860, y2=160),
    Rect(x1=710, y1=110, x2=830, y2=160),
]

# ==============================================================================
# Invariant UI Verification Landmarks
# ==============================================================================
LANDMARK_MINIMAP = Point(x=30, y=18)
LANDMARK_AUCTION_HEADER = Point(x=100, y=120)
LANDMARK_SIDEBAR_GREEN_BUTTON = Rect(x1=280, y1=535, x2=340, y2=558)
LANDMARK_TOP_LEAVE_BUTTON = Rect(x1=975, y1=32, x2=1040, y2=48)

# Price Sort Direction Arrow Pixels
SORT_ARROW_TOP = Rect(x1=974, y1=170, x2=982, y2=174)     # Lit = Descending
SORT_ARROW_BOTTOM = Rect(x1=974, y1=177, x2=982, y2=181)  # Lit = Ascending

# ==============================================================================
# Table Row & Column Grid Slices (Canonical 1280x720)
# ==============================================================================
# 7 listing rows displayed on each page
ROW_BOUNDS_1280: List[Tuple[int, int]] = [
    (193, 251),
    (252, 310),
    (311, 368),
    (370, 427),
    (428, 486),
    (487, 545),
    (546, 603),
]

# Legacy reference row bounds on 1024x576 canvas
ROW_BOUNDS_1024: List[Tuple[int, int]] = [
    (155, 201),
    (202, 248),
    (249, 295),
    (296, 342),
    (343, 389),
    (390, 436),
    (437, 483),
]

# Column X-ranges on 1024x576 reference grid
COL_ITEM_NAME_1024 = (365, 555)
COL_QUANTITY_1024 = (560, 620)
COL_UNIT_PRICE_1024 = (710, 845)
COL_TOTAL_PRICE_1024 = (850, 990)
COL_MATCHED_UNIT_PRICE_1024 = (620, 765)
COL_TRADE_TIME_1024 = (775, 955)

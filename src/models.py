from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class ActiveListing(BaseModel):
    """
    Represents an active sell listing from the '查詢' (Query / Listings) tab.
    """
    item_name: str
    quantity: int = 1
    total_price: int
    unit_price: int
    remaining_time: Optional[str] = None
    seller_id: Optional[str] = None
    page_number: Optional[int] = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)

class MatchedTrade(BaseModel):
    """
    Represents a historical completed transaction from the '市價' (Market / Match Price) tab.
    """
    item_name: str
    quantity: int = 1
    matched_unit_price: int
    total_matched_price: Optional[int] = None
    trade_time: Optional[str] = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)

class SearchQuota(BaseModel):
    """
    Tracks market search quota status (e.g. 499 / 500).
    """
    current_used: int
    max_limit: int
    captured_at: datetime = Field(default_factory=datetime.utcnow)

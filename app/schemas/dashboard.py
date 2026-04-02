from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DashboardRecentItem(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime
    detail_count: int


class DashboardSummaryRead(BaseModel):
    phones_total: int
    phones_working: int
    messages_sent: int
    messages_received: int
    sends_pending: int
    sends_failed: int
    campaigns_active: int
    train_active: int
    latest_campaign: Optional[DashboardRecentItem] = None
    latest_train: Optional[DashboardRecentItem] = None

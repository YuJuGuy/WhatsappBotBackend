from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


# ──────────────────────────────────────────────
# Campaign schemas
# ──────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    template_id: Optional[int] = None
    template_group_id: Optional[int] = None
    use_group: bool = False
    phone_ids: Optional[List[int]] = None         # individual phone IDs
    phone_group_ids: Optional[List[int]] = None    # group IDs (resolved to phone IDs on backend)
    phone_column: str                              # which XLSX column has recipient numbers
    variable_mapping: Dict[str, str] = {}          # {"template_var": "xlsx_column"}
    scheduled_at: datetime
    sheet_name: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class CampaignRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    template_id: Optional[int] = None
    template_group_id: Optional[int] = None
    use_group: bool
    sender_phone_ids: List[int] = []
    scheduled_at: datetime
    created_at: datetime
    recipient_count: int = 0

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Campaign Recipient schemas
# ──────────────────────────────────────────────

class CampaignRecipientRead(BaseModel):
    id: int
    phone_number: str
    row_data: Dict = {}
    rendered_message: str = ""
    status: str = "pending"
    error_message: Optional[str] = None
    sent_by_session_name: Optional[str] = None
    sent_by_number: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Campaign Resend schemas
# ──────────────────────────────────────────────

class CampaignResendRequest(BaseModel):
    recipient_ids: List[int]
    phone_ids: Optional[List[int]] = None
    phone_group_ids: Optional[List[int]] = None
    scheduled_at: datetime

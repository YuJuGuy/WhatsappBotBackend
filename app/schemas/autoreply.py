from pydantic import BaseModel, Field as PydanticField
from typing import Optional
from datetime import datetime

from app.models.autoreply import enumMatchType


# ── Message Auto Reply Rule ──

class MessageAutoReplyCreate(BaseModel):
    trigger_text: str
    match_type: enumMatchType = enumMatchType.contains
    response_text: str
    is_active: bool = True
    priority: int = 50
    rule_priority: int = 0

class MessageAutoReplyUpdate(BaseModel):
    trigger_text: Optional[str] = None
    match_type: Optional[enumMatchType] = None
    response_text: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None
    rule_priority: Optional[int] = None

class MessageAutoReplyRead(BaseModel):
    id: int
    trigger_text: str
    match_type: enumMatchType
    response_text: str
    is_active: bool
    priority: int
    rule_priority: int
    created_at: datetime
    user_id: int

    class Config:
        from_attributes = True


# ── Webhook Payload ──
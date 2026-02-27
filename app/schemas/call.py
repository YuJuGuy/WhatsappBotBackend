from pydantic import BaseModel, Field as PydanticField
from typing import Optional


# ── Auto Call Reply Config ──

class AutoCallReplyCreate(BaseModel):
    enabled: bool = False
    process_groups: bool = False
    default_template_id: int
    priority: int = 50

class AutoCallReplyUpdate(BaseModel):
    enabled: Optional[bool] = None
    process_groups: Optional[bool] = None
    default_template_id: Optional[int] = None
    priority: Optional[int] = None

class AutoCallReplyRead(BaseModel):
    id: int
    enabled: bool
    process_groups: bool
    default_template_id: int
    priority: int


# ── Webhook Payload ──

class CallWebhookPayload(BaseModel):
    id: str
    from_number: str = PydanticField(alias="from")
    timestamp: int
    isVideo: bool = False
    isGroup: bool = False

    class Config:
        extra = "allow"
        populate_by_name = True

class CallWebhookEvent(BaseModel):
    event: str
    session: str
    payload: CallWebhookPayload

    class Config:
        extra = "allow"

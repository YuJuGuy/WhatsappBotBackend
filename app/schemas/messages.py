from pydantic import BaseModel, Field as PydanticField
from typing import Optional

class MessageWebhookPayload(BaseModel):
    id: str
    from_number: str = PydanticField(alias="from")
    timestamp: int = 0
    fromMe: bool = False
    to: Optional[str] = None
    body: str = ""
    hasMedia: bool = False

    class Config:
        extra = "allow"
        populate_by_name = True

class MeInfo(BaseModel):
    id: str
    pushName: Optional[str] = None

class MessageWebhookEvent(BaseModel):
    event: str
    session: str
    payload: MessageWebhookPayload
    me: Optional[MeInfo] = None
    user_id: Optional[int] = None

    class Config:
        extra = "allow"

from datetime import datetime

class MessageRead(BaseModel):
    id: int
    session_id: str
    phone_name: Optional[str] = None
    from_number: str
    to_number: str
    message_body: str
    from_me: bool
    user_id: int
    timestamp: datetime

    class Config:
        from_attributes = True

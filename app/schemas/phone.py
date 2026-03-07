from pydantic import BaseModel
from typing import Optional, List


# ──────────────────────────────────────────────
# Phone schemas
# ──────────────────────────────────────────────

class PhoneBase(BaseModel):
    name: str
    description: Optional[str] = None


class PhoneInfo(PhoneBase):
    id: int
    status: Optional[str] = None
    session_id: str
    number: Optional[str] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Phone Group schemas
# ──────────────────────────────────────────────

class PhoneGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    phone_ids: Optional[List[int]] = None


class PhoneGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    phone_ids: Optional[List[int]] = None


class PhoneGroupRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    phones: List[PhoneInfo] = []

    class Config:
        from_attributes = True

# ──────────────────────────────────────────────
# Webhook Schemas
# ──────────────────────────────────────────────

class MeInfo(BaseModel):
    id: str
    pushName: Optional[str] = None

class SessionStatusPayload(BaseModel):
    status: str
    statuses: Optional[list] = []

class SessionStatusWebhookEvent(BaseModel):
    event: str
    session: str
    me: Optional[MeInfo] = None
    payload: SessionStatusPayload
    engine: Optional[str] = None
    environment: Optional[dict] = None
    user_id: Optional[int] = None

    class Config:
        extra = "allow"

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from app.models.tickets import ShareStatus

# User Schema for nesting
class UserReadBasic(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
    
# ── Ticket Category ──
class TicketCategoryCreate(BaseModel):
    name: str
    color: str = "#6b7280"

class TicketCategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class TicketCategoryRead(BaseModel):
    id: int
    name: str
    color: str
    user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
# ── Ticket ──
class TicketCreate(BaseModel):
    category_id: Optional[int] = None
    sender_number: str
    body: str

class TicketUpdate(BaseModel):
    category_id: Optional[int] = None
    is_open: Optional[bool] = None

class TicketRead(BaseModel):
    id: int
    user_id: int
    category_id: Optional[int]
    sender_number: str
    phone_name: Optional[str] = None
    body: str
    is_open: bool
    created_at: datetime
    # We might nest the category to show the color easily
    category: Optional[TicketCategoryRead] = None
    user: Optional[UserReadBasic] = None
    model_config = ConfigDict(from_attributes=True)

# ── Ticket Share ──
class TicketInboxInviteCreate(BaseModel):
    email: str

class TicketInboxShareRead(BaseModel):
    id: int
    owner_id: int
    shared_with_id: int
    status: ShareStatus
    created_at: datetime
    owner: Optional[UserReadBasic] = None
    shared_with: Optional[UserReadBasic] = None

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
import enum


class enumMatchType(str, enum.Enum):
    exact = "exact"
    contains = "contains"
    starts_with = "starts_with"
    ends_with = "ends_with"


class AutoReplyPhoneLink(SQLModel, table=True):
    rule_id: int = Field(foreign_key="messageautoreplyrule.id", primary_key=True, ondelete="CASCADE")
    phone_id: int = Field(foreign_key="phone.id", primary_key=True, ondelete="CASCADE")


class MessageAutoReplyRule(SQLModel, table=True):
    """Rules for auto-replying to incoming messages."""
    id: Optional[int] = Field(default=None, primary_key=True)
    trigger_text: str
    match_type: enumMatchType = Field(default=enumMatchType.contains)
    response_text: str

    is_active: bool = True

    priority: int = Field(default=50)
    rule_priority: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    user_id: int = Field(foreign_key="user.id")

    user: Optional["User"] = Relationship(back_populates="autoreplies")

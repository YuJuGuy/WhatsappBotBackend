from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.phone import Phone, Group
    from app.models.settings import Settings
    from app.models.template import Template, TemplateGroup
    from app.models.campaign import Campaign
    from app.models.call import CallAutoReplyConfig
    from app.models.autoreply import MessageAutoReplyRule
    from app.models.outbox import OutboxMessage
    from app.models.blacklist import Blacklist

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    full_name: Optional[str] = None
    
    # Relationships
    phones: List["Phone"] = Relationship(back_populates="user")
    groups: List["Group"] = Relationship(back_populates="user")
    settings: Optional["Settings"] = Relationship(back_populates="user")
    templates: List["Template"] = Relationship(back_populates="user")
    template_groups: List["TemplateGroup"] = Relationship(back_populates="user")
    campaigns: List["Campaign"] = Relationship(back_populates="user")
    auto_call_reply: Optional["CallAutoReplyConfig"] = Relationship(back_populates="user")
    autoreplies: List["MessageAutoReplyRule"] = Relationship(back_populates="user")
    outbox_messages: List["OutboxMessage"] = Relationship(back_populates="user")
    blacklist: List["Blacklist"] = Relationship(back_populates="user")

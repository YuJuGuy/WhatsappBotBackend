import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User

class ShareStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class TicketInboxShare(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    shared_with_id: int = Field(foreign_key="user.id")
    status: ShareStatus = Field(default=ShareStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    owner: Optional["User"] = Relationship(back_populates="shared_inboxes_out", sa_relationship_kwargs={"foreign_keys": "[TicketInboxShare.owner_id]"})
    shared_with: Optional["User"] = Relationship(back_populates="shared_inboxes_in", sa_relationship_kwargs={"foreign_keys": "[TicketInboxShare.shared_with_id]"})

class TicketCategory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    color: str = Field(default="#6b7280") # Default generic gray hex color
    user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional["User"] = Relationship(back_populates="ticket_categories")
    tickets: list["Ticket"] = Relationship(back_populates="category", cascade_delete=True)

class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    category_id: Optional[int] = Field(default=None, foreign_key="ticketcategory.id", ondelete="SET NULL")
    sender_number: str
    session_id: Optional[str] = Field(default=None)
    body: str
    is_open: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional["User"] = Relationship(back_populates="tickets")
    category: Optional[TicketCategory] = Relationship(back_populates="tickets")

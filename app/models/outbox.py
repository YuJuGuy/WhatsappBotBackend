from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.campaign import Campaign

class OutboxMessage(SQLModel, table=True):
    __tablename__ = "outbox_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    
    # Use SQLAlchemy's JSONB for the payload column
    payload: Any = Field(sa_column=Column(JSONB))
    
    # Store backup session IDs (List[str]) in case the primary one gets blocked/fails
    fallback_session_ids: Any = Field(default=[], sa_column=Column(JSONB, server_default='[]'))
    
    scheduled_at: datetime = Field(index=True)
    status: str = Field(default="pending", index=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    not_before_at: Optional[datetime] = None
    leased_until: Optional[datetime] = Field(default=None, index=True)
    
    user_id: int = Field(foreign_key="user.id", index=True)
    priority: int = Field(default=100, index=True)
    
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="outbox_messages")
    campaign: Optional["Campaign"] = Relationship(back_populates="outbox_messages")

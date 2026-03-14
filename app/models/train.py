from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.outbox import OutboxMessage


class TrainSession(SQLModel, table=True):
    __tablename__ = "train_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None)
    status: str = Field(default="generating", index=True)

    session_id_1: str = Field(index=True)
    session_id_2: str = Field(index=True)
    phone_number_1: str = Field(default="")
    phone_number_2: str = Field(default="")

    total_days: int = Field(default=1)
    messages_per_day: int = Field(default=50)

    scheduled_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = Field(default=None)

    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="train_sessions")
    messages: List["TrainMessage"] = Relationship(back_populates="train_session")
    outbox_messages: List["OutboxMessage"] = Relationship(back_populates="train_session")


class TrainMessage(SQLModel, table=True):
    __tablename__ = "train_message"

    id: Optional[int] = Field(default=None, primary_key=True)
    train_session_id: int = Field(foreign_key="train_session.id", index=True)

    sender_session_id: str = Field(index=True)
    receiver_phone_number: str = Field(default="")
    text: str = Field(default="")

    day_number: int = Field(default=1)
    position: int = Field(default=0)
    scheduled_at_offset: str = Field(default="00:00")
    scheduled_at: Optional[datetime] = None

    status: str = Field(default="pending", index=True)
    error_message: Optional[str] = Field(default=None)
    sent_by_session_name: Optional[str] = Field(default=None)
    sent_by_number: Optional[str] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)

    # Relationships
    train_session: Optional["TrainSession"] = Relationship(back_populates="messages")

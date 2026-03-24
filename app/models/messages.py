from typing import Optional
from sqlalchemy import Index
from sqlmodel import SQLModel, Field





from datetime import datetime, timezone

class Messages(SQLModel, table=True):
    __table_args__ = (
        Index("ix_messages_user_timestamp", "user_id", "timestamp"),
        Index("uq_messages_session_waha_message_id", "session_id", "waha_message_id", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    waha_message_id: str = Field(index=True)
    session_id: str
    from_number: str
    to_number: str = ""
    message_body: str
    from_me: bool
    user_id: int = Field(index=True, foreign_key="user.id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

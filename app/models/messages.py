from typing import Optional
from sqlmodel import SQLModel, Field





from datetime import datetime, timezone

class Messages(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    waha_message_id: str = ""
    session_id: str
    from_number: str
    to_number: str = ""
    message_body: str
    from_me: bool
    user_id: int = Field(index=True, foreign_key="user.id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from app.models.user import User

class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    delay: bool = Field(default=False)
    min_delay_seconds: int = Field(default=1)
    max_delay_seconds: int = Field(default=5)
    sleep: bool = Field(default=False)
    sleep_after_messages: int = Field(default=1)
    min_sleep_seconds: int = Field(default=1)
    max_sleep_seconds: int = Field(default=5)


    # Relationships
    user_id: int = Field(foreign_key="user.id")


    # Relationships
    user: Optional["User"] = Relationship(back_populates="settings")
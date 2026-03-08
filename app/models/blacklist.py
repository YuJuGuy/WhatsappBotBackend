from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.user import User



class Blacklist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.now)


    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="blacklist")

    
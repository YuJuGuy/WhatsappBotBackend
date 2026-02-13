from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.phone_group_link import PhoneGroupLink

class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    
    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="groups")
    phone_links: List["PhoneGroupLink"] = Relationship(back_populates="group")

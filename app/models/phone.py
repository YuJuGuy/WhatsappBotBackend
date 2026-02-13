from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.group import Group
    from app.models.phone_group_link import PhoneGroupLink

class Phone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    session_id: str = Field(index=True, unique=True, nullable=False)
    number: str = Field(index=True)
    description: Optional[str] = None
    status: Optional[str] = None
    
    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="phones")
    group_links: List["PhoneGroupLink"] = Relationship(back_populates="phone")

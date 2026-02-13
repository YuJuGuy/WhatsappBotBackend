from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.phone import Phone
    from app.models.group import Group

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

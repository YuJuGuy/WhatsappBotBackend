from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.phone import Phone
    from app.models.group import Group

class PhoneGroupLink(SQLModel, table=True):
    """Many-to-many link table between Phone and Group."""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    phone_id: int = Field(foreign_key="phone.id", index=True)
    group_id: int = Field(foreign_key="group.id", index=True)
    
    # Relationships
    phone: Optional["Phone"] = Relationship(back_populates="group_links")
    group: Optional["Group"] = Relationship(back_populates="phone_links")

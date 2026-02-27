from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User


class PhoneGroupLink(SQLModel, table=True):
    """Many-to-many link table between Phone and Group."""
    id: Optional[int] = Field(default=None, primary_key=True)

    phone_id: int = Field(foreign_key="phone.id", index=True)
    group_id: int = Field(foreign_key="group.id", index=True)

    # Relationships
    phone: Optional["Phone"] = Relationship(back_populates="group_links")
    group: Optional["Group"] = Relationship(back_populates="phone_links")


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


class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None

    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="groups")
    phone_links: List["PhoneGroupLink"] = Relationship(back_populates="group")

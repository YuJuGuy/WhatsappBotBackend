from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User


class TemplateGroupLink(SQLModel, table=True):
    """Many-to-many link table between Template and TemplateGroup."""
    id: Optional[int] = Field(default=None, primary_key=True)

    template_id: int = Field(foreign_key="template.id", index=True)
    template_group_id: int = Field(foreign_key="templategroup.id", index=True)
    position: int = Field(default=0)

    # Relationships
    template: Optional["Template"] = Relationship(back_populates="group_links")
    template_group: Optional["TemplateGroup"] = Relationship(back_populates="template_links")


class Template(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    body: str
    is_archived: bool = Field(default=False, index=True)

    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="templates")
    group_links: List["TemplateGroupLink"] = Relationship(back_populates="template")


class TemplateGroup(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None

    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="template_groups")
    template_links: List["TemplateGroupLink"] = Relationship(back_populates="template_group")

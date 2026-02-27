from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.template import Template


class AutoCallReply(SQLModel, table=True):
    """User-level config for auto-replying to declined calls."""
    id: Optional[int] = Field(default=None, primary_key=True)
    enabled: bool = Field(default=False)
    process_groups: bool = Field(default=False)
    default_template_id: int = Field(foreign_key="template.id")
    priority: int = Field(default=50)

    # Foreign key to User (one config per user)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="auto_call_reply")
    default_template: Optional["Template"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AutoCallReply.default_template_id]"}
    )

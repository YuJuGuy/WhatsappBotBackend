from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User


def _default_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=7)


class StoredFile(SQLModel, table=True):
    __tablename__ = "stored_file"

    id: Optional[int] = Field(default=None, primary_key=True)
    original_name: str = Field(index=True)
    stored_name: str = Field(index=True)
    relative_path: str
    content_type: Optional[str] = Field(default=None)
    size_bytes: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(default_factory=_default_expiry, index=True)

    user_id: int = Field(foreign_key="user.id", index=True)

    user: Optional["User"] = Relationship(back_populates="stored_files")

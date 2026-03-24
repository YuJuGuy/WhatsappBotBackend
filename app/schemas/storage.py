from datetime import datetime
from pydantic import BaseModel


class StoredFileRead(BaseModel):
    id: int
    original_name: str
    content_type: str | None = None
    size_bytes: int
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True

from datetime import datetime
from sqlmodel import SQLModel, Field

class RefreshToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    revoked: bool = Field(default=False, index=True)

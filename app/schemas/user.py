from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from app.core.features import Feature

class UserBase(BaseModel):
    email: EmailStr
    is_active: bool = True
    is_superuser: bool = False
    full_name: Optional[str] = None
    expiry_date: Optional[date] = None
    allowed_features: list[Feature] = Field(default_factory=list)

class UserCreate(UserBase):
    password: str

class AdminUserCreate(UserCreate):
    pass


class AdminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    full_name: Optional[str] = None
    expiry_date: Optional[date] = None
    allowed_features: Optional[list[Feature]] = None

class UserRead(UserBase):
    id: int

class UserLogin(BaseModel):
    email: EmailStr
    password: str

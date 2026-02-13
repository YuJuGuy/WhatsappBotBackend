from pydantic import BaseModel
from typing import Optional


class PhoneBase(BaseModel):
    name: str
    description: Optional[str] = None
    

class PhoneInfo(PhoneBase):
    id: int
    status: Optional[str] = None
    session_id: str
    number: Optional[str] = None
    
    class Config:
        from_attributes = True


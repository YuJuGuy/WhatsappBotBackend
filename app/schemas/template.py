from pydantic import BaseModel
from typing import Optional, List


# ──────────────────────────────────────────────
# Template schemas
# ──────────────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str
    body: str


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None


class TemplateRead(BaseModel):
    id: int
    name: str
    body: str

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Template Group schemas
# ──────────────────────────────────────────────

class TemplateGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    template_ids: Optional[List[int]] = None


class TemplateGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template_ids: Optional[List[int]] = None


class TemplateGroupRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    templates: List[TemplateRead] = []

    class Config:
        from_attributes = True

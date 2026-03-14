from pydantic import BaseModel, model_validator
from typing import Optional, List, Literal
from datetime import datetime


class ProviderConfig(BaseModel):
    """LLM provider configuration. Required fields depend on provider_type."""
    provider_type: Literal["azure", "openai", "ollama", "gemini"]
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    model: str

    @model_validator(mode="after")
    def validate_provider_fields(self):
        t = self.provider_type
        if t == "azure" and (not self.api_key or not self.endpoint):
            raise ValueError("Azure provider requires api_key and endpoint")
        if t == "openai" and not self.api_key:
            raise ValueError("OpenAI provider requires api_key")
        if t == "ollama" and not self.endpoint:
            raise ValueError("Ollama provider requires endpoint")
        if t == "gemini" and not self.api_key:
            raise ValueError("Gemini provider requires api_key")
        return self


# ── Generate (kick off background generation) ────────────

class TrainGenerateRequest(BaseModel):
    session_id_1: str
    session_id_2: str
    days: int = 1
    messages_per_day: int = 50
    provider: ProviderConfig


# ── Start (push generated messages to outbox) ────────────

class TrainStartRequest(BaseModel):
    scheduled_at: datetime


# ── Read / List ──────────────────────────────────────────

class TrainMessageRead(BaseModel):
    id: int
    sender_session_id: str
    receiver_phone_number: str
    text: str
    day_number: int
    position: int
    scheduled_at_offset: str = "00:00"
    scheduled_at: Optional[datetime] = None
    status: str
    error_message: Optional[str] = None
    sent_by_session_name: Optional[str] = None
    sent_by_number: Optional[str] = None
    updated_at: Optional[datetime] = None


class TrainSessionRead(BaseModel):
    id: int
    name: Optional[str] = None
    status: str
    session_id_1: str
    session_id_2: str
    phone_number_1: str
    phone_number_2: str
    total_days: int
    messages_per_day: int
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    error_message: Optional[str] = None
    message_count: int = 0

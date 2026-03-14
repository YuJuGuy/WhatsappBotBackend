from sqlmodel import SQLModel
from pydantic import field_validator
from typing import Optional
from datetime import datetime
import phonenumbers


class BlacklistBase(SQLModel):
    phone_number: str


import phonenumbers
from sqlmodel import SQLModel
from pydantic import field_validator


class BlacklistCreate(SQLModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            # ensure it has +
            if not v.startswith("+"):
                v = "+" + v

            parsed = phonenumbers.parse(v, None)

            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Invalid phone number")

            # normalize to digits only
            normalized = f"{parsed.country_code}{parsed.national_number}"
            return normalized.lstrip("+")

        except phonenumbers.NumberParseException:
            raise ValueError("Invalid phone number")
class BlacklistRead(BlacklistBase):
    id: int
    created_at: datetime


class BulkBlacklistRequest(SQLModel):
    phone_numbers: list[str] = []
    recipient_ids: list[int] = []

class BulkBlacklistDeleteRequest(SQLModel):
    blacklist_ids: list[int]
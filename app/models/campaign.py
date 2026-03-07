from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.outbox import OutboxMessage


class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    status: str = Field(default="scheduled")  # scheduled, active, paused, completed

    # Template (single or group)
    template_id: Optional[int] = Field(default=None, foreign_key="template.id")
    template_group_id: Optional[int] = Field(default=None, foreign_key="templategroup.id")
    use_group: bool = Field(default=False)

    # Sender phones — resolved list of phone IDs (stored as JSON string e.g. "[1, 3, 5]")
    sender_phone_ids: str = Field(default="[]")

    # XLSX mapping
    phone_column: str = Field(default="")         # which column has recipient numbers
    variable_mapping: str = Field(default="{}")    # JSON: {"template_var": "xlsx_column"}

    # Scheduling
    scheduled_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Foreign key to User
    user_id: int = Field(foreign_key="user.id", index=True)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="campaigns")
    recipients: List["CampaignRecipient"] = Relationship(back_populates="campaign")
    outbox_messages: List["OutboxMessage"] = Relationship(back_populates="campaign")


class CampaignRecipient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    phone_number: str = Field(index=True)
    row_data: str = Field(default="{}")  # JSON: full XLSX row {"Col A": "Ahmed", "Col B": "Riyadh"}

    # Reporting fields
    rendered_message: str = Field(default="")       # The actual personalized message text
    status: str = Field(default="pending")           # pending, sent, failed
    error_message: Optional[str] = Field(default=None)  # Why it failed (from WAHA)
    
    # Track which session successfully sent the message
    sent_by_session_name: Optional[str] = Field(default=None)
    sent_by_number: Optional[str] = Field(default=None)
    
    updated_at: Optional[datetime] = Field(default=None)  # When the status changed

    # Foreign key to Campaign
    campaign_id: int = Field(foreign_key="campaign.id", index=True)

    # Relationships
    campaign: Optional["Campaign"] = Relationship(back_populates="recipients")

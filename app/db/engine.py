import os
from sqlmodel import SQLModel, create_engine, Session
from app.models.user import User
from app.models.phone import Phone, Group, PhoneGroupLink
from app.models.settings import Settings
from app.models.template import Template, TemplateGroup, TemplateGroupLink
from app.models.campaign import Campaign, CampaignRecipient
from app.models.call import CallAutoReplyConfig
from app.models.autoreply import MessageAutoReplyRule
from app.models.outbox import OutboxMessage

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:22101975@localhost:5432/postgres")

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

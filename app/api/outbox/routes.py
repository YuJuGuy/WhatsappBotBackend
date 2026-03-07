from fastapi import APIRouter
from sqlmodel import Session
from datetime import datetime
from typing import List, Dict, Any

from app.api.deps import get_session
from app.models.outbox import OutboxMessage

router = APIRouter()

def insert_outbox(session_id: str, payload: dict, scheduled_at: datetime, user_id: int, priority: int, session: Session = None) -> int:
    """
    Insert a single message into outbox_messages table using SQLModel.
    """
    close_session = False
    if session is None:
        session = next(get_session())
        close_session = True
        
    try:
        outbox = OutboxMessage(
            session_id=session_id,
            payload=payload,
            scheduled_at=scheduled_at,
            user_id=user_id,
            priority=priority
        )

        session.add(outbox)
        session.commit()
        session.refresh(outbox)
        return outbox.id
    finally:
        if close_session:
            session.close()


def bulk_insert_outbox(messages: List[Dict[str, Any]], batch_size: int = 1000, session: Session = None) -> None:
    """
    Bulk insert messages into outbox_messages table.
    messages: List of dicts with keys: session_id, payload, scheduled_at, user_id, priority
    """
    if not messages:
        return []

    close_session = False
    if session is None:
        session = next(get_session())
        close_session = True
    
    try:
        outbox_list = []
        for msg in messages:
            outbox_list.append(
                OutboxMessage(
                    session_id=msg["session_id"],
                    payload=msg["payload"],
                    scheduled_at=msg["scheduled_at"],
                    user_id=msg["user_id"],
                    priority=msg.get("priority", 100),
                    campaign_id=msg.get("campaign_id"),
                    fallback_session_ids=msg.get("fallback_session_ids", [])
                )
            )
        
        session.add_all(outbox_list)
        session.commit()
    finally:
        if close_session:
            session.close()



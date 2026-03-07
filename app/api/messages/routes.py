from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user
from app.models.user import User
from app.models.phone import Phone
from app.models.messages import Messages
from app.schemas.messages import MessageRead, MessageWebhookEvent


router = APIRouter()

@router.get("/")
def get_messages(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = Query(200, description="Max messages to return to prevent DB crashing")
):
    """Get all messages for the current user."""
    stmt = (
        select(Messages, Phone.name)
        .outerjoin(Phone, Messages.session_id == Phone.session_id)
        .where(Messages.user_id == current_user.id)
        .order_by(Messages.timestamp.desc())
        .limit(limit)
    )
    results = session.exec(stmt).all()
    
    messages_out = []
    for msg, phone_name in results:
        msg_dict = msg.model_dump()
        msg_dict["phone_name"] = phone_name or msg.session_id
        messages_out.append(MessageRead(**msg_dict))
        
    return messages_out


def save_message(event: MessageWebhookEvent):
    """Save a message to the database."""
    session = next(get_session())
    try:
        message = Messages(
            session_id=event.session,
            from_number=event.payload.from_number,
            message_body=event.payload.body,
            from_me=event.payload.fromMe,
            user_id=event.user_id
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return message
    finally:
        session.close()
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime, timezone
from sqlalchemy import or_

from app.api.deps import get_session, get_current_user, require_feature
from app.core.features import Feature
from app.models.user import User
from app.models.phone import Phone
from app.models.messages import Messages
from app.schemas.messages import MessageRead, MessageWebhookEvent


router = APIRouter(dependencies=[Depends(require_feature(Feature.messages))])

@router.get("/")
def get_messages(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    page_size: int = Query(50, ge=1, le=200, description="Number of items per page"),
    session_id: str | None = Query(default=None, description="Filter messages by sender session"),
    search: str | None = Query(default=None, description="Search term for message body or numbers")
):
    """Get paginated messages for the current user."""
    stmt = (
        select(Messages, Phone.name)
        .outerjoin(Phone, Messages.session_id == Phone.session_id)
        .where(Messages.user_id == current_user.id)
    )

    if session_id:
        stmt = stmt.where(Messages.session_id == session_id)

    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Messages.message_body.ilike(search_term),
                Messages.from_number.ilike(search_term),
                Messages.to_number.ilike(search_term),
                Phone.name.ilike(search_term)
            )
        )

    # Fetch one extra to determine has_more
    stmt = stmt.order_by(Messages.timestamp.desc()).offset((page - 1) * page_size).limit(page_size + 1)

    results = session.exec(stmt).all()
    
    has_more = len(results) > page_size
    items_to_return = results[:page_size]

    messages_out = []
    for msg, phone_name in items_to_return:
        msg_dict = msg.model_dump()
        msg_dict["phone_name"] = phone_name or msg.session_id
        messages_out.append(MessageRead(**msg_dict))
        
    return {
        "items": messages_out,
        "has_more": has_more,
        "page": page,
        "page_size": page_size
    }


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

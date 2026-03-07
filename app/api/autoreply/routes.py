from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user
from app.api.outbox.routes import insert_outbox
from app.models.user import User
from app.models.phone import Phone
from app.models.messages import Messages
from app.models.autoreply import MessageAutoReplyRule
from app.schemas.autoreply import MessageAutoReplyCreate, MessageAutoReplyUpdate, MessageAutoReplyRead
from app.schemas.messages import MessageWebhookEvent


router = APIRouter()

@router.post("/", response_model=MessageAutoReplyRead)
def create_autoreply(
    data: MessageAutoReplyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new message auto-reply rule."""
    rule = MessageAutoReplyRule(
        **data.model_dump(),
        user_id=current_user.id
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.get("/", response_model=list[MessageAutoReplyRead])
def get_autoreplies(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get all auto-reply rules for the current user."""
    rules = session.exec(
        select(MessageAutoReplyRule).where(MessageAutoReplyRule.user_id == current_user.id)
    ).all()
    return rules


@router.get("/{rule_id}", response_model=MessageAutoReplyRead)
def get_autoreply(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific auto-reply rule."""
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{rule_id}", response_model=MessageAutoReplyRead)
def update_autoreply(
    rule_id: int,
    data: MessageAutoReplyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update an auto-reply rule."""
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_autoreply(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete an auto-reply rule."""
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    session.delete(rule)
    session.commit()
    return {"detail": "Rule deleted"}


async def message_webhook(event: MessageWebhookEvent):
    """Called directly from the global webhook handler - NOT a route."""
    session_id = event.session
    raw_from = event.payload.from_number
                 
    from_number = raw_from.split("@")[0]
    message_body = event.payload.body
    from_me = event.payload.fromMe

    # Skip messages sent by us
    if from_me:
        print(f"[Webhook] Skipping own message")
        return

    # Manually get a DB session (Depends doesn't work outside routes)

    session = next(get_session())
    try:
        # Find the phone by session_id
        phone = session.exec(
            select(Phone).where(Phone.session_id == session_id)
        ).first()
        if not phone:
            print(f"[Webhook] Phone not found for session: {session_id}")
            return

        # Also skip if from our own number
        if phone.number and from_number == phone.number:
            print(f"[Webhook] Skipping message from own number")
            return

        print(f"[Webhook] Found phone: id={phone.id}, user_id={phone.user_id}")

        # Get active rules ordered by priority (highest first)
        rules = session.exec(
            select(MessageAutoReplyRule)
            .where(MessageAutoReplyRule.user_id == phone.user_id, MessageAutoReplyRule.is_active == True)
            .order_by(MessageAutoReplyRule.rule_priority.desc())
        ).all()
        if not rules:
            print(f"[Webhook] No rules found for user: {phone.user_id}")
            return

        print(f"[Webhook] Found {len(rules)} rules for user: {phone.user_id}")

        # Find matching rule
        rule_to_use = None
        for rule in rules:
            if rule.match_type == "exact":
                if message_body == rule.trigger_text:
                    rule_to_use = rule
                    break
            elif rule.match_type == "contains":
                if rule.trigger_text in message_body:
                    rule_to_use = rule
                    break
            elif rule.match_type == "starts_with":
                if message_body.startswith(rule.trigger_text):
                    rule_to_use = rule
                    break
            elif rule.match_type == "ends_with":
                if message_body.endswith(rule.trigger_text):
                    rule_to_use = rule
                    break

        if rule_to_use:
            now = datetime.now(timezone.utc)
            outbox_id = insert_outbox(
                session_id=session_id,
                payload={
                    "to": from_number,
                    "text": rule_to_use.response_text,
                },
                scheduled_at=now,
                user_id=phone.user_id,
                priority=rule_to_use.priority
            )
            print(f"[Webhook] Outbox message created: id={outbox_id}")
        else:
            print(f"[Webhook] No rule matched for message: {message_body}")
    finally:
        session.close()


def save_message(event: MessageWebhookEvent):
    """Save a message to the database."""
    # Skip saving if no user_id was provided in the headers
    if not event.user_id:
        print("[Webhook] Skipping save_message: No user_id in webhook headers")
        return None

    session = next(get_session())
    try:
        # WAHA behavior:
        #   payload.from = ALWAYS the other person in the chat
        #   me.id        = ALWAYS you (the bot)
        #
        # So:
        #   fromMe=True  → you sent it  → from=me.id, to=payload.from
        #   fromMe=False → they sent it → from=payload.from, to=me.id

        # 1. Get the "other person" number (payload.from)
        other_raw = event.payload.from_number

        # Resolve @lid → real number via _data.Info.Chat
        if other_raw.endswith("@lid") and getattr(event.payload, "_data", None):
            _data = event.payload._data
            if isinstance(_data, dict):
                chat = _data.get("Info", {}).get("Chat", "")
                if chat and not chat.endswith("@lid"):
                    other_raw = chat

        other_number = other_raw.split("@")[0]

        # 2. Get the bot's own number from me.id
        me_number = ""
        if event.me and event.me.id:
            me_number = event.me.id.split("@")[0]

        # 3. Assign from/to based on direction
        if event.payload.fromMe:
            from_number = me_number
            to_number = other_number
        else:
            from_number = other_number
            to_number = me_number

        print(f"[Webhook] Parsed from_number: {from_number}, to_number: {to_number}")
        
        message_timestamp = datetime.now(timezone.utc)
        if event.payload.timestamp > 0:
            try:
                message_timestamp = datetime.fromtimestamp(event.payload.timestamp, tz=timezone.utc)
            except Exception:
                pass
                
        message = Messages(
            waha_message_id=event.payload.id,
            session_id=event.session,
            from_number=from_number,
            to_number=to_number,
            message_body=event.payload.body,
            from_me=event.payload.fromMe,
            user_id=event.user_id,
            timestamp=message_timestamp
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        print(f"[Webhook] Saved message: id={message.id}")
        return message
    except Exception as e:
        print(f"[Webhook] Error saving message: {e}")
        return None
    finally:
        session.close()

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user
from app.api.outbox.routes import insert_outbox
from app.models.user import User
from app.models.phone import Phone
from app.models.messages import Messages
from app.models.autoreply import MessageAutoReplyRule, AutoReplyPhoneLink
from app.schemas.autoreply import MessageAutoReplyCreate, MessageAutoReplyUpdate, MessageAutoReplyRead
from app.schemas.messages import MessageWebhookEvent


router = APIRouter()


def _get_phone_ids(session: Session, rule_id: int) -> List[int]:
    links = session.exec(
        select(AutoReplyPhoneLink).where(AutoReplyPhoneLink.rule_id == rule_id)
    ).all()
    return [l.phone_id for l in links]


def _sync_phone_links(session: Session, rule_id: int, phone_ids: List[int]):
    old = session.exec(
        select(AutoReplyPhoneLink).where(AutoReplyPhoneLink.rule_id == rule_id)
    ).all()
    for link in old:
        session.delete(link)
    session.flush()
    for pid in phone_ids:
        session.add(AutoReplyPhoneLink(rule_id=rule_id, phone_id=pid))


@router.post("/")
def create_autoreply(
    data: MessageAutoReplyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not data.phone_ids:
        raise HTTPException(status_code=400, detail="يجب اختيار رقم واحد على الأقل")

    for pid in data.phone_ids:
        phone = session.get(Phone, pid)
        if not phone or phone.user_id != current_user.id:
            raise HTTPException(status_code=400, detail=f"الرقم {pid} غير موجود أو لا يخصك")

    rule_data = data.model_dump(exclude={"phone_ids"})
    rule = MessageAutoReplyRule(**rule_data, user_id=current_user.id)
    session.add(rule)
    session.flush()

    for pid in data.phone_ids:
        session.add(AutoReplyPhoneLink(rule_id=rule.id, phone_id=pid))

    session.commit()
    return {"success": True, "id": rule.id}


@router.get("/", response_model=list[MessageAutoReplyRead])
def get_autoreplies(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    rules = session.exec(
        select(MessageAutoReplyRule).where(MessageAutoReplyRule.user_id == current_user.id)
    ).all()
    return [
        MessageAutoReplyRead(
            id=r.id,
            trigger_text=r.trigger_text,
            match_type=r.match_type,
            response_text=r.response_text,
            is_active=r.is_active,
            priority=r.priority,
            rule_priority=r.rule_priority,
            created_at=r.created_at,
            user_id=r.user_id,
            phone_ids=_get_phone_ids(session, r.id),
        )
        for r in rules
    ]


@router.get("/{rule_id}", response_model=MessageAutoReplyRead)
def get_autoreply(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return MessageAutoReplyRead(
        id=rule.id,
        trigger_text=rule.trigger_text,
        match_type=rule.match_type,
        response_text=rule.response_text,
        is_active=rule.is_active,
        priority=rule.priority,
        rule_priority=rule.rule_priority,
        created_at=rule.created_at,
        user_id=rule.user_id,
        phone_ids=_get_phone_ids(session, rule.id),
    )


@router.put("/{rule_id}")
def update_autoreply(
    rule_id: int,
    data: MessageAutoReplyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = data.model_dump(exclude_unset=True, exclude={"phone_ids"})
    for key, value in update_data.items():
        setattr(rule, key, value)

    if data.phone_ids is not None:
        if not data.phone_ids:
            raise HTTPException(status_code=400, detail="يجب اختيار رقم واحد على الأقل")
        for pid in data.phone_ids:
            phone = session.get(Phone, pid)
            if not phone or phone.user_id != current_user.id:
                raise HTTPException(status_code=400, detail=f"الرقم {pid} غير موجود أو لا يخصك")
        _sync_phone_links(session, rule.id, data.phone_ids)

    session.add(rule)
    session.commit()
    return {"success": True}


@router.delete("/{rule_id}")
def delete_autoreply(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    rule = session.get(MessageAutoReplyRule, rule_id)
    if not rule or rule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(rule)
    session.commit()
    return {"success": True}


async def message_webhook(event: MessageWebhookEvent):
    """Called directly from the global webhook handler - NOT a route."""
    session_id = event.session
    raw_from = event.payload.from_number
    from_chat_id = raw_from if "@" in raw_from else f"{raw_from}@c.us"

    real_from = raw_from
    if raw_from.endswith("@lid") and getattr(event.payload, "_data", None):
        _data = event.payload._data
        if isinstance(_data, dict):
            info = _data.get("Info", {})
            sender_alt = info.get("SenderAlt", "")
            if sender_alt and not sender_alt.endswith("@lid"):
                bare = sender_alt.split(":")[0].split("@")[0]
                real_from = sender_alt
                from_chat_id = f"{bare}@c.us"
            else:
                chat = info.get("Chat", "")
                if chat and not chat.endswith("@lid"):
                    bare = chat.split(":")[0].split("@")[0]
                    real_from = chat
                    from_chat_id = f"{bare}@c.us"

    from_number_bare = real_from.split(":")[0].split("@")[0]
    message_body = event.payload.body
    from_me = event.payload.fromMe

    if from_me:
        print(f"[Webhook] Skipping own message")
        return

    session = next(get_session())
    try:
        phone = session.exec(
            select(Phone).where(Phone.session_id == session_id)
        ).first()
        if not phone:
            print(f"[Webhook] Phone not found for session: {session_id}")
            return

        if phone.number and from_number_bare == phone.number:
            print(f"[Webhook] Skipping message from own number")
            return

        print(f"[Webhook] Found phone: id={phone.id}, user_id={phone.user_id}")

        rules = session.exec(
            select(MessageAutoReplyRule)
            .join(AutoReplyPhoneLink, AutoReplyPhoneLink.rule_id == MessageAutoReplyRule.id)
            .where(
                AutoReplyPhoneLink.phone_id == phone.id,
                MessageAutoReplyRule.is_active == True,
            )
            .order_by(MessageAutoReplyRule.rule_priority.desc())
        ).all()
        if not rules:
            print(f"[Webhook] No rules found for phone: {phone.id}")
            return

        print(f"[Webhook] Found {len(rules)} rules for phone: {phone.id}")

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
                    "to": from_chat_id,
                    "text": rule_to_use.response_text,
                },
                scheduled_at=now,
                user_id=phone.user_id,
                priority=rule_to_use.priority,
            )
            print(f"[Webhook] Outbox message created: id={outbox_id}")
        else:
            print(f"[Webhook] No rule matched for message: {message_body}")
    finally:
        session.close()


def save_message(event: MessageWebhookEvent):
    """Save a message to the database."""
    if not event.user_id:
        print("[Webhook] Skipping save_message: No user_id in webhook headers")
        return None

    session = next(get_session())
    try:
        other_raw = event.payload.from_number

        if other_raw.endswith("@lid") and getattr(event.payload, "_data", None):
            _data = event.payload._data
            if isinstance(_data, dict):
                info = _data.get("Info", {})
                sender_alt = info.get("SenderAlt", "")
                if sender_alt and not sender_alt.endswith("@lid"):
                    other_raw = sender_alt
                else:
                    chat = info.get("Chat", "")
                    if chat and not chat.endswith("@lid"):
                        other_raw = chat

        other_number = other_raw.split(":")[0].split("@")[0]

        me_number = ""
        if event.me and event.me.id:
            me_number = event.me.id.split("@")[0]

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
            timestamp=message_timestamp,
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

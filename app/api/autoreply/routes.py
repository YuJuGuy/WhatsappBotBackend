from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from sqlalchemy import func, literal
from typing import List
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user, require_feature, user_has_feature
from app.core.features import Feature
from app.api.outbox.routes import insert_outbox
from app.models.user import User
from app.models.phone import Phone
from app.models.messages import Messages
from app.models.autoreply import MessageAutoReplyRule, AutoReplyPhoneLink, enumMatchType
from app.schemas.autoreply import MessageAutoReplyCreate, MessageAutoReplyUpdate, MessageAutoReplyRead
from app.schemas.messages import MessageWebhookEvent
from app.api.rate_limit import rate_limit_by_user


router = APIRouter(dependencies=[Depends(require_feature(Feature.auto_reply))])


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


def _find_best_matching_rule(session: Session, phone_id: int, message_body: str):
    # Fetch all active rules for this specific phone (usually a very small number, e.g., 5-20)
    rules = session.exec(
        select(MessageAutoReplyRule)
        .join(AutoReplyPhoneLink, AutoReplyPhoneLink.rule_id == MessageAutoReplyRule.id)
        .where(
            AutoReplyPhoneLink.phone_id == phone_id,
            MessageAutoReplyRule.is_active == True,
        )
    ).all()

    if not rules:
        return None

    candidates = []
    message_body_lower = message_body.lower()
    
    for rule in rules:
        trigger = rule.trigger_text.lower()
        if rule.match_type == "exact" and trigger == message_body_lower:
            candidates.append(rule)
        elif rule.match_type == "starts_with" and message_body_lower.startswith(trigger):
            candidates.append(rule)
        elif rule.match_type == "ends_with" and message_body_lower.endswith(trigger):
            candidates.append(rule)
        elif rule.match_type == "contains" and trigger in message_body_lower:
            candidates.append(rule)

    if not candidates:
        return None

    # Return the rule with the lowest priority number, breaking ties with lowest ID
    return min(candidates, key=lambda rule: (rule.rule_priority, rule.id))


@router.post("/", dependencies=[Depends(rate_limit_by_user(20, 60, "autoreply-create"))])
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


@router.put("/{rule_id}", dependencies=[Depends(rate_limit_by_user(20, 60, "autoreply-update"))])
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


@router.delete("/{rule_id}", dependencies=[Depends(rate_limit_by_user(20, 60, "autoreply-delete"))])
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


async def message_webhook(event: MessageWebhookEvent, is_sandbox: bool = False):
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

        print(f"[Webhook] Found phone: id={phone.id}, user_id={phone.user_id}")

        user = session.get(User, phone.user_id)
        if not user or not user_has_feature(user, Feature.auto_reply):
            print(f"[Webhook] Skipping auto-reply for disabled feature")
            return

        rule_to_use = _find_best_matching_rule(session, phone.id, message_body)

        if rule_to_use:
            if is_sandbox:
                return rule_to_use.response_text
                
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
                source_feature=Feature.auto_reply.value,
            )
            print(f"[Webhook] Outbox message created: id={outbox_id}")
        else:
            print(f"[Webhook] No rule matched for message: {message_body}")
        return None
    finally:
        session.close()


def save_message(event: MessageWebhookEvent):
    """Save a message to the database."""
    if not event.user_id:
        print("[Webhook] Skipping save_message: No user_id in webhook headers")
        return None, False

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
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            print(f"[Webhook] Duplicate message skipped: waha_message_id={event.payload.id}")
            return None, False
        session.refresh(message)
        print(f"[Webhook] Saved message: id={message.id}")
        return message, True
    except Exception as e:
        print(f"[Webhook] Error saving message: {e}")
        return None, False
    finally:
        session.close()

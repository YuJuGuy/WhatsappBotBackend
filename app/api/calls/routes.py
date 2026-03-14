from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user
from app.models.call import CallAutoReplyConfig, CallConfigPhoneLink
from app.models.template import Template
from app.models.phone import Phone
from app.models.user import User
from app.schemas.call import (
    CallAutoReplyCreate, CallAutoReplyUpdate, CallAutoReplyRead,
    CallWebhookEvent
)
from app.api.outbox.routes import insert_outbox
from app.utils.waha import reject_call

router = APIRouter()


def _get_phone_ids(session: Session, config_id: int) -> List[int]:
    links = session.exec(
        select(CallConfigPhoneLink).where(CallConfigPhoneLink.config_id == config_id)
    ).all()
    return [l.phone_id for l in links]


def _sync_phone_links(session: Session, config_id: int, phone_ids: List[int]):
    old = session.exec(
        select(CallConfigPhoneLink).where(CallConfigPhoneLink.config_id == config_id)
    ).all()
    for link in old:
        session.delete(link)
    session.flush()
    for pid in phone_ids:
        session.add(CallConfigPhoneLink(config_id=config_id, phone_id=pid))


# ──────────────────────────────────────────────
# List all configs
# ──────────────────────────────────────────────

@router.get("/", response_model=List[CallAutoReplyRead])
def list_configs(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    configs = session.exec(
        select(CallAutoReplyConfig).where(CallAutoReplyConfig.user_id == current_user.id)
    ).all()
    return [
        CallAutoReplyRead(
            id=c.id,
            enabled=c.enabled,
            process_groups=c.process_groups,
            default_template_id=c.default_template_id,
            priority=c.priority,
            phone_ids=_get_phone_ids(session, c.id),
        )
        for c in configs
    ]


# ──────────────────────────────────────────────
# Create config
# ──────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_config(
    data: CallAutoReplyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not data.phone_ids:
        raise HTTPException(status_code=400, detail="يجب اختيار رقم واحد على الأقل")

    for pid in data.phone_ids:
        phone = session.get(Phone, pid)
        if not phone or phone.user_id != current_user.id:
            raise HTTPException(status_code=400, detail=f"الرقم {pid} غير موجود أو لا يخصك")
        existing = session.exec(
            select(CallConfigPhoneLink).where(CallConfigPhoneLink.phone_id == pid)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"الرقم {phone.name} مرتبط بقاعدة رفض أخرى بالفعل")

    template = session.get(Template, data.default_template_id)
    if not template or template.user_id != current_user.id:
        raise HTTPException(status_code=400, detail="القالب غير موجود أو لا يخصك")

    config = CallAutoReplyConfig(
        enabled=data.enabled,
        process_groups=data.process_groups,
        default_template_id=data.default_template_id,
        priority=data.priority,
        user_id=current_user.id,
    )
    session.add(config)
    session.flush()

    for pid in data.phone_ids:
        session.add(CallConfigPhoneLink(config_id=config.id, phone_id=pid))

    session.commit()
    return {"success": True, "id": config.id}


# ──────────────────────────────────────────────
# Update config
# ──────────────────────────────────────────────

@router.put("/{config_id}")
def update_config(
    config_id: int,
    data: CallAutoReplyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    config = session.get(CallAutoReplyConfig, config_id)
    if not config or config.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="الإعداد غير موجود")

    if data.enabled is not None:
        config.enabled = data.enabled
    if data.process_groups is not None:
        config.process_groups = data.process_groups
    if data.default_template_id is not None:
        template = session.get(Template, data.default_template_id)
        if not template or template.user_id != current_user.id:
            raise HTTPException(status_code=400, detail="القالب غير موجود أو لا يخصك")
        config.default_template_id = data.default_template_id
    if data.priority is not None:
        config.priority = data.priority

    if data.phone_ids is not None:
        if not data.phone_ids:
            raise HTTPException(status_code=400, detail="يجب اختيار رقم واحد على الأقل")
        for pid in data.phone_ids:
            phone = session.get(Phone, pid)
            if not phone or phone.user_id != current_user.id:
                raise HTTPException(status_code=400, detail=f"الرقم {pid} غير موجود أو لا يخصك")
            existing = session.exec(
                select(CallConfigPhoneLink).where(
                    CallConfigPhoneLink.phone_id == pid,
                    CallConfigPhoneLink.config_id != config.id,
                )
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"الرقم {phone.name} مرتبط بقاعدة رفض أخرى بالفعل")
        _sync_phone_links(session, config.id, data.phone_ids)

    session.add(config)
    session.commit()
    return {"success": True}


# ──────────────────────────────────────────────
# Delete config
# ──────────────────────────────────────────────

@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    config_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    config = session.get(CallAutoReplyConfig, config_id)
    if not config or config.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="الإعداد غير موجود")
    session.delete(config)
    session.commit()
    return None


# ──────────────────────────────────────────────
# Webhook: Call Received
# ──────────────────────────────────────────────

async def call_webhook(event: CallWebhookEvent):
    session = next(get_session())
    try:
        session_id = event.session
        raw_from = event.payload.from_number
        from_chat_id = raw_from if "@" in raw_from else f"{raw_from}@c.us"

        if raw_from.endswith("@lid") and getattr(event.payload, "_data", None):
            _data = event.payload._data
            if isinstance(_data, dict):
                info = _data.get("Info", {})
                sender_alt = info.get("SenderAlt", "")
                if sender_alt and not sender_alt.endswith("@lid"):
                    bare = sender_alt.split(":")[0].split("@")[0]
                    from_chat_id = f"{bare}@c.us"
                else:
                    chat = info.get("Chat", "")
                    if chat and not chat.endswith("@lid"):
                        bare = chat.split(":")[0].split("@")[0]
                        from_chat_id = f"{bare}@c.us"

        phone = session.exec(
            select(Phone).where(Phone.session_id == session_id)
        ).first()
        if not phone:
            print(f"[Webhook] Phone not found for session: {session_id}")
            return {"status": "error", "reason": f"Phone with session '{session_id}' not found"}
        print(f"[Webhook] Found phone: id={phone.id}, user_id={phone.user_id}")

        config = session.exec(
            select(CallAutoReplyConfig)
            .join(CallConfigPhoneLink, CallConfigPhoneLink.config_id == CallAutoReplyConfig.id)
            .where(
                CallConfigPhoneLink.phone_id == phone.id,
                CallAutoReplyConfig.enabled == True,
            )
        ).first()
        if not config:
            print(f"[Webhook] No enabled call config for phone {phone.id}")
            return {"status": "ignored", "reason": "No call config for this phone"}
        print(f"[Webhook] Config {config.id} matched, template_id={config.default_template_id}")

        if event.payload.isGroup and not config.process_groups:
            print(f"[Webhook] Skipping group call")
            return {"status": "ignored", "reason": "Group calls are not processed"}

        try:
            result = await reject_call(session_id, from_chat_id, event.payload.id)
            print(f"[Webhook] Call rejected: {result}")
        except Exception as e:
            print(f"[Webhook] Failed to reject call: {e}")

        template = session.get(Template, config.default_template_id)
        if not template:
            print(f"[Webhook] Template not found: {config.default_template_id}")
            return {"status": "error", "reason": "Template not found"}

        now = datetime.now(timezone.utc)
        outbox_id = insert_outbox(
            session_id=session_id,
            payload={
                "to": from_chat_id,
                "text": template.body,
            },
            scheduled_at=now,
            user_id=phone.user_id,
            priority=config.priority,
        )

        print(f"[Webhook] Outbox message created: id={outbox_id}")
        return {"status": "ok", "outbox_id": outbox_id}
    finally:
        session.close()

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from datetime import datetime, timezone

from app.api.deps import get_session, get_current_user
from app.models.call import CallAutoReplyConfig
from app.models.template import Template
from app.models.phone import Phone
from app.models.user import User
from app.schemas.call import (
    CallAutoReplyCreate, CallAutoReplyUpdate, CallAutoReplyRead,
    CallWebhookEvent
)
from app.api.outbox.routes import insert_outbox
from app.utils.waha import reject_call
from app.utils.hmac_verify import verify_webhook_hmac

router = APIRouter()


# ──────────────────────────────────────────────
# Calls Config CRUD
# ──────────────────────────────────────────────

@router.get("/")
def get_config(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get the user's auto call reply config."""
    config = session.exec(
        select(CallAutoReplyConfig).where(CallAutoReplyConfig.user_id == current_user.id)
    ).first()
    if not config:
        return None
    return config


@router.post("/", response_model=CallAutoReplyRead, status_code=status.HTTP_201_CREATED)
def create_config(
    data: CallAutoReplyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create the user's auto call reply config."""
    existing = session.exec(
        select(CallAutoReplyConfig).where(CallAutoReplyConfig.user_id == current_user.id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Config already exists. Use PUT to update.")

    template = session.get(Template, data.default_template_id)
    if not template or template.user_id != current_user.id:
        raise HTTPException(status_code=400, detail="Default template not found or not owned by you")

    config = CallAutoReplyConfig(
        enabled=data.enabled,
        process_groups=data.process_groups,
        default_template_id=data.default_template_id,
        priority=data.priority,
        user_id=current_user.id
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


@router.put("/", response_model=CallAutoReplyRead)
def update_config(
    data: CallAutoReplyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update the user's auto call reply config."""
    config = session.exec(
        select(CallAutoReplyConfig).where(CallAutoReplyConfig.user_id == current_user.id)
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="Auto call reply config not found")

    if data.enabled is not None:
        config.enabled = data.enabled
    if data.process_groups is not None:
        config.process_groups = data.process_groups
    if data.default_template_id is not None:
        template = session.get(Template, data.default_template_id)
        if not template or template.user_id != current_user.id:
            raise HTTPException(status_code=400, detail="Default template not found or not owned by you")
        config.default_template_id = data.default_template_id
    if data.priority is not None:
        config.priority = data.priority

    session.add(config)
    session.commit()
    session.refresh(config)
    return config


# ──────────────────────────────────────────────
# Webhook: Call Received
# ──────────────────────────────────────────────

async def call_webhook(event: CallWebhookEvent):
    session = next(get_session())
    try:
        session_id = event.session
        from_number = event.payload.from_number

        # Find the phone by session_id
        phone = session.exec(
            select(Phone).where(Phone.session_id == session_id)
        ).first()
        if not phone:
            print(f"[Webhook] Phone not found for session: {session_id}")
            return {"status": "error", "reason": f"Phone with session '{session_id}' not found"}
        print(f"[Webhook] Found phone: id={phone.id}, user_id={phone.user_id}")

        # Find the user's auto call reply config
        config = session.exec(
            select(CallAutoReplyConfig).where(CallAutoReplyConfig.user_id == phone.user_id)
        ).first()
        if not config or not config.enabled:
            print(f"[Webhook] Config: {'not found' if not config else 'disabled'}")
            return {"status": "ignored", "reason": "Auto call reply is disabled"}
        print(f"[Webhook] Config enabled, template_id={config.default_template_id}, priority={config.priority}")

        # Skip group calls if not allowed
        if event.payload.isGroup and not config.process_groups:
            print(f"[Webhook] Skipping group call")
            return {"status": "ignored", "reason": "Group calls are not processed"}

        # Reject the call via WAHA client
        try:
            result = await reject_call(session_id, from_number, event.payload.id)
            print(f"[Webhook] Call rejected: {result}")
        except Exception as e:
            print(f"[Webhook] Failed to reject call: {e}")

        # Get the template
        template = session.get(Template, config.default_template_id)
        if not template:
            print(f"[Webhook] Template not found: {config.default_template_id}")
            return {"status": "error", "reason": "Template not found"}

        # Insert outbox message
        now = datetime.now(timezone.utc)
        outbox_id = insert_outbox(
            session_id=session_id,
            payload={
                "to": from_number,
                "text": template.body,
            },
            scheduled_at=now,
            user_id=phone.user_id,
            priority=config.priority
        )

        print(f"[Webhook] Outbox message created: id={outbox_id}")
        return {"status": "ok", "outbox_id": outbox_id}
    finally:
        session.close()

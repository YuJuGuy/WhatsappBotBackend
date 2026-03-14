from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, select, update

from app.schemas.train import (
    TrainGenerateRequest, TrainStartRequest,
    TrainSessionRead, TrainMessageRead, ProviderConfig,
)
from app.api.deps import get_session, get_current_user
from app.models.user import User
from app.models.phone import Phone
from app.models.train import TrainSession, TrainMessage
from app.models.outbox import OutboxMessage
from app.api.train.generator import process_train_session
from app.api.train.chat_generator import create_provider, validate_provider

router = APIRouter()


# ──────────────────────────────────────────────
# Generate (creates session + generates messages)
# ──────────────────────────────────────────────

@router.post("/generate", status_code=status.HTTP_201_CREATED)
def generate_train(
    req: TrainGenerateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    phone_1 = session.exec(
        select(Phone).where(Phone.session_id == req.session_id_1, Phone.user_id == current_user.id)
    ).first()
    if not phone_1:
        raise HTTPException(status_code=404, detail=f"Phone with session_id '{req.session_id_1}' not found")
    if phone_1.status != "WORKING":
        raise HTTPException(status_code=400, detail=f"Phone '{phone_1.name}' is not WORKING (status: {phone_1.status})")

    phone_2 = session.exec(
        select(Phone).where(Phone.session_id == req.session_id_2, Phone.user_id == current_user.id)
    ).first()
    if not phone_2:
        raise HTTPException(status_code=404, detail=f"Phone with session_id '{req.session_id_2}' not found")
    if phone_2.status != "WORKING":
        raise HTTPException(status_code=400, detail=f"Phone '{phone_2.name}' is not WORKING (status: {phone_2.status})")

    try:
        provider = create_provider(
            provider_type=req.provider.provider_type,
            model=req.provider.model,
            api_key=req.provider.api_key,
            endpoint=req.provider.endpoint,
        )
        validate_provider(provider)
    except Exception as e:
        err = str(e).lower()
        if "api key" in err or "api_key" in err or "unauthorized" in err or "401" in err or "invalid_argument" in err:
            msg = "مفتاح API غير صالح. يرجى التحقق من المفتاح والمحاولة مرة أخرى."
        elif "not found" in err or "404" in err or "model" in err:
            msg = "النموذج أو الرابط غير صحيح. يرجى التحقق من اسم النموذج والرابط."
        elif "connection" in err or "connect" in err or "timeout" in err or "unreachable" in err:
            msg = "لا يمكن الاتصال بمزود الذكاء الاصطناعي. يرجى التحقق من الرابط والمحاولة مرة أخرى."
        elif "rate" in err or "quota" in err or "429" in err:
            msg = "تم تجاوز حد الاستخدام لمزود الذكاء الاصطناعي. يرجى المحاولة لاحقاً."
        elif "permission" in err or "403" in err or "forbidden" in err:
            msg = "ليس لديك صلاحية للوصول إلى هذا المزود. يرجى التحقق من الصلاحيات."
        else:
            msg = "فشل التحقق من مزود الذكاء الاصطناعي. يرجى التحقق من الإعدادات والمحاولة مرة أخرى."
        raise HTTPException(status_code=400, detail=msg)

    train_session = TrainSession(
        name=f"Train {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        status="generating",
        session_id_1=req.session_id_1,
        session_id_2=req.session_id_2,
        phone_number_1=phone_1.number,
        phone_number_2=phone_2.number,
        total_days=req.days,
        messages_per_day=req.messages_per_day,
        user_id=current_user.id,
    )
    session.add(train_session)
    session.commit()
    session.refresh(train_session)

    # Returns immediately — generation runs in background.
    # Later: swap internals with HTTP call to Azure Function.
    process_train_session(train_session.id, req.provider.model_dump())

    return {"success": True, "train_session_id": train_session.id}


# ──────────────────────────────────────────────
# Start (push generated messages to outbox)
# ──────────────────────────────────────────────

@router.post("/{train_session_id}/start", status_code=status.HTTP_200_OK)
def start_train(
    train_session_id: int,
    req: TrainStartRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if ts.status != "generated":
        raise HTTPException(status_code=400, detail=f"Train session is not ready (status: {ts.status})")

    messages = session.exec(
        select(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    ).all()

    if not messages:
        raise HTTPException(status_code=400, detail="No messages found for this train session")

    scheduled_at = req.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    ts.scheduled_at = scheduled_at

    outbox_entries: list[dict] = []
    for msg in messages:
        parts = (msg.scheduled_at_offset or "00:00").split(":")
        hours = int(parts[0]) if len(parts) > 0 else 0
        minutes = int(parts[1]) if len(parts) > 1 else 0

        day_base = scheduled_at + timedelta(days=msg.day_number - 1)
        msg_scheduled_at = day_base + timedelta(hours=hours, minutes=minutes)

        msg.scheduled_at = msg_scheduled_at
        session.add(msg)

        outbox_entries.append({
            "session_id": msg.sender_session_id,
            "fallback_session_ids": [],
            "payload": {
                "to": msg.receiver_phone_number,
                "text": msg.text,
                "train_message_id": msg.id,
            },
            "scheduled_at": msg_scheduled_at,
            "user_id": current_user.id,
            "priority": 50,
            "train_id": ts.id,
        })

    ts.status = "scheduled"
    session.add(ts)
    session.commit()

    if outbox_entries:
        from app.api.outbox.routes import bulk_insert_outbox
        bulk_insert_outbox(outbox_entries)

    return {"success": True}


# ──────────────────────────────────────────────
# List all train sessions
# ──────────────────────────────────────────────

@router.get("/", response_model=List[TrainSessionRead])
def list_train_sessions(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    sessions_list = session.exec(
        select(TrainSession).where(TrainSession.user_id == current_user.id)
    ).all()

    result = []
    dirty = False
    for ts in sessions_list:
        msg_count = len(session.exec(
            select(TrainMessage).where(TrainMessage.train_session_id == ts.id)
        ).all())

        if ts.status == "scheduled":
            pending_count = len(session.exec(
                select(TrainMessage).where(
                    TrainMessage.train_session_id == ts.id,
                    TrainMessage.status == "pending",
                )
            ).all())
            if msg_count > 0 and pending_count == 0:
                ts.status = "finished"
                session.add(ts)
                dirty = True

        result.append(TrainSessionRead(
            id=ts.id,
            name=ts.name,
            status=ts.status,
            session_id_1=ts.session_id_1,
            session_id_2=ts.session_id_2,
            phone_number_1=ts.phone_number_1,
            phone_number_2=ts.phone_number_2,
            total_days=ts.total_days,
            messages_per_day=ts.messages_per_day,
            scheduled_at=ts.scheduled_at,
            created_at=ts.created_at,
            error_message=ts.error_message,
            message_count=msg_count,
        ))

    if dirty:
        session.commit()

    return result


# ──────────────────────────────────────────────
# Get single train session (with full report + messages)
# ──────────────────────────────────────────────

@router.get("/{train_session_id}")
def get_train_session(
    train_session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    messages = session.exec(
        select(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    ).all()

    total = len(messages)
    sent = sum(1 for m in messages if m.status == "sent")
    failed = sum(1 for m in messages if m.status == "failed")
    pending = sum(1 for m in messages if m.status == "pending")
    cancelled = sum(1 for m in messages if m.status == "cancelled")
    skipped = sum(1 for m in messages if m.status == "skipped")

    if ts.status == "scheduled" and total > 0 and pending == 0:
        ts.status = "finished"
        session.add(ts)
        session.commit()

    return {
        "session": TrainSessionRead(
            id=ts.id,
            name=ts.name,
            status=ts.status,
            session_id_1=ts.session_id_1,
            session_id_2=ts.session_id_2,
            phone_number_1=ts.phone_number_1,
            phone_number_2=ts.phone_number_2,
            total_days=ts.total_days,
            messages_per_day=ts.messages_per_day,
            scheduled_at=ts.scheduled_at,
            created_at=ts.created_at,
            error_message=ts.error_message,
            message_count=total,
        ),
        "summary": {
            "total": total,
            "sent": sent,
            "failed": failed,
            "pending": pending,
            "cancelled": cancelled,
            "skipped": skipped,
        },
        "messages": [
            TrainMessageRead(
                id=m.id,
                sender_session_id=m.sender_session_id,
                receiver_phone_number=m.receiver_phone_number,
                text=m.text,
                day_number=m.day_number,
                position=m.position,
                scheduled_at_offset=m.scheduled_at_offset,
                scheduled_at=m.scheduled_at,
                status=m.status,
                error_message=m.error_message,
                sent_by_session_name=m.sent_by_session_name,
                sent_by_number=m.sent_by_number,
                updated_at=m.updated_at,
            )
            for m in messages
        ],
    }


# ──────────────────────────────────────────────
# Retry a failed train session
# ──────────────────────────────────────────────

@router.post("/{train_session_id}/retry", status_code=status.HTTP_200_OK)
def retry_train(
    train_session_id: int,
    req: ProviderConfig,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if ts.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed sessions can be retried")

    try:
        provider = create_provider(
            provider_type=req.provider_type,
            model=req.model,
            api_key=req.api_key,
            endpoint=req.endpoint,
        )
        validate_provider(provider)
    except Exception as e:
        err = str(e).lower()
        if "api key" in err or "api_key" in err or "unauthorized" in err or "401" in err or "invalid_argument" in err:
            msg = "مفتاح API غير صالح. يرجى التحقق من المفتاح والمحاولة مرة أخرى."
        elif "not found" in err or "404" in err or "model" in err:
            msg = "النموذج أو الرابط غير صحيح. يرجى التحقق من اسم النموذج والرابط."
        elif "connection" in err or "connect" in err or "timeout" in err or "unreachable" in err:
            msg = "لا يمكن الاتصال بمزود الذكاء الاصطناعي. يرجى التحقق من الرابط والمحاولة مرة أخرى."
        elif "rate" in err or "quota" in err or "429" in err:
            msg = "تم تجاوز حد الاستخدام لمزود الذكاء الاصطناعي. يرجى المحاولة لاحقاً."
        elif "permission" in err or "403" in err or "forbidden" in err:
            msg = "ليس لديك صلاحية للوصول إلى هذا المزود. يرجى التحقق من الصلاحيات."
        else:
            msg = "فشل التحقق من مزود الذكاء الاصطناعي. يرجى التحقق من الإعدادات والمحاولة مرة أخرى."
        raise HTTPException(status_code=400, detail=msg)

    old_messages = session.exec(
        select(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    ).all()
    for m in old_messages:
        session.delete(m)

    ts.status = "generating"
    ts.error_message = None
    session.add(ts)
    session.commit()

    process_train_session(ts.id, req.model_dump())

    return {"success": True, "train_session_id": ts.id}


# ──────────────────────────────────────────────
# Cancel a train session
# ──────────────────────────────────────────────

@router.post("/{train_session_id}/cancel")
def cancel_train_session(
    train_session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if ts.status in ["finished", "cancelled"]:
        raise HTTPException(status_code=400, detail="Train session is already finished or cancelled")

    ts.status = "cancelled"
    session.add(ts)

    session.exec(
        update(OutboxMessage)
        .where(OutboxMessage.train_id == ts.id)
        .where(OutboxMessage.status.in_(["pending", "queued"]))
        .values(status="cancelled")
    )

    session.exec(
        update(TrainMessage)
        .where(TrainMessage.train_session_id == ts.id)
        .where(TrainMessage.status == "pending")
        .values(status="cancelled", error_message="Train session cancelled")
    )

    session.commit()

    return {"success": True}


# ──────────────────────────────────────────────
# Delete a train session (only if not yet started)
# ──────────────────────────────────────────────

@router.delete("/{train_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_train_session(
    train_session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if ts.status == "scheduled":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active train session. Cancel it first."
        )

    messages = session.exec(
        select(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    ).all()
    for m in messages:
        session.delete(m)

    session.delete(ts)
    session.commit()
    return None

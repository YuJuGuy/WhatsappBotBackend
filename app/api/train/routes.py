from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, select, update
from sqlalchemy import case, func

from app.schemas.train import (
    TrainGenerateRequest, TrainStartRequest,
    TrainSessionRead, TrainMessageRead, ProviderConfig, TrainUpdateRequest
)
from app.api.deps import get_session, get_current_user, require_feature
from app.core.features import Feature
from app.models.user import User
from app.models.phone import Phone
from app.models.train import TrainSession, TrainMessage
from app.models.outbox import OutboxMessage
from app.api.train.generator import process_train_session
from app.api.train.chat_generator import create_provider, validate_provider
from app.api.rate_limit import rate_limit_by_user

router = APIRouter(dependencies=[Depends(require_feature(Feature.train))])


def _serialize_train_message(message: TrainMessage) -> TrainMessageRead:
    return TrainMessageRead(
        id=message.id,
        receiver_phone_number=message.receiver_phone_number,
        text=message.text,
        day_number=message.day_number,
        position=message.position,
        scheduled_at_offset=message.scheduled_at_offset,
        scheduled_at=message.scheduled_at,
        status=message.status,
        error_message=message.error_message,
        sent_by_session_name=message.sent_by_session_name,
        sent_by_number=message.sent_by_number,
        updated_at=message.updated_at,
    )


def _get_train_phone_map(session: Session, user_id: int, session_ids: list[str]) -> dict[str, Phone]:
    if not session_ids:
        return {}

    phones = session.exec(
        select(Phone).where(
            Phone.user_id == user_id,
            Phone.session_id.in_(session_ids),
        )
    ).all()
    return {phone.session_id: phone for phone in phones}


def _build_train_session_read(ts: TrainSession, message_count: int, phone_map: dict[str, Phone]) -> TrainSessionRead:
    phone_1 = phone_map.get(ts.session_id_1)
    phone_2 = phone_map.get(ts.session_id_2)

    return TrainSessionRead(
        id=ts.id,
        name=ts.name,
        status=ts.status,
        phone_name_1=phone_1.name if phone_1 else None,
        phone_name_2=phone_2.name if phone_2 else None,
        total_days=ts.total_days,
        messages_per_day=ts.messages_per_day,
        scheduled_at=ts.scheduled_at,
        created_at=ts.created_at,
        error_message=ts.error_message,
        message_count=message_count,
    )


def _get_train_summary(session: Session, train_session_id: int) -> dict:
    counts = session.exec(
        select(TrainMessage.status, func.count(TrainMessage.id))
        .where(TrainMessage.train_session_id == train_session_id)
        .group_by(TrainMessage.status)
    ).all()

    summary = {
        "total": 0,
        "sent": 0,
        "failed": 0,
        "pending": 0,
        "paused": 0,
        "cancelled": 0,
        "skipped": 0,
    }

    for status_name, count in counts:
        summary["total"] += count
        if status_name in summary:
            summary[status_name] = count

    return summary


def _get_train_day_summaries(session: Session, train_session_id: int) -> list[dict]:
    rows = session.exec(
        select(
            TrainMessage.day_number,
            func.count(TrainMessage.id),
            func.sum(case((TrainMessage.status == "sent", 1), else_=0)),
            func.sum(case((TrainMessage.status == "failed", 1), else_=0)),
            func.sum(case((TrainMessage.status == "pending", 1), else_=0)),
            func.sum(case((TrainMessage.status == "paused", 1), else_=0)),
            func.sum(case((TrainMessage.status == "cancelled", 1), else_=0)),
            func.sum(case((TrainMessage.status == "skipped", 1), else_=0)),
        )
        .where(TrainMessage.train_session_id == train_session_id)
        .group_by(TrainMessage.day_number)
        .order_by(TrainMessage.day_number.asc())
    ).all()

    return [
        {
            "day_number": day_number,
            "total": total,
            "sent": sent or 0,
            "failed": failed or 0,
            "pending": pending or 0,
            "paused": paused or 0,
            "cancelled": cancelled or 0,
            "skipped": skipped or 0,
        }
        for day_number, total, sent, failed, pending, paused, cancelled, skipped in rows
    ]


# ──────────────────────────────────────────────
# Generate (creates session + generates messages)
# ──────────────────────────────────────────────

@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_by_user(5, 60, "train-generate"))],
)
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
        name=req.name.strip() if req.name and req.name.strip() else f"Train {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
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

@router.post(
    "/{train_session_id}/start",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_by_user(5, 60, "train-start"))],
)
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
            "source_feature": Feature.train.value,
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
# Update a train session
# ──────────────────────────────────────────────

@router.put("/{train_session_id}")
def update_train_session(
    train_session_id: int,
    req: TrainUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    ts.name = req.name.strip() if req.name else ts.name
    session.add(ts)
    session.commit()

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
    phone_map = _get_train_phone_map(
        session,
        current_user.id,
        [sid for ts in sessions_list for sid in (ts.session_id_1, ts.session_id_2)],
    )

    session_ids = [ts.id for ts in sessions_list if ts.id is not None]
    counts_by_session = {}
    pending_by_session = {}
    if session_ids:
        stats_rows = session.exec(
            select(
                TrainMessage.train_session_id,
                func.count(TrainMessage.id),
                func.sum(case((TrainMessage.status == "pending", 1), else_=0)),
            )
            .where(TrainMessage.train_session_id.in_(session_ids))
            .group_by(TrainMessage.train_session_id)
        ).all()
        counts_by_session = {session_id: total for session_id, total, _pending in stats_rows}
        pending_by_session = {session_id: pending or 0 for session_id, _total, pending in stats_rows}

    result = []
    dirty = False
    for ts in sessions_list:
        msg_count = counts_by_session.get(ts.id, 0)

        if ts.status == "scheduled":
            pending_count = pending_by_session.get(ts.id, 0)
            if msg_count > 0 and pending_count == 0:
                ts.status = "finished"
                session.add(ts)
                dirty = True

        result.append(_build_train_session_read(ts, msg_count, phone_map))

    if dirty:
        session.commit()

    return result


# ──────────────────────────────────────────────
# Get single train session (with full report + messages)
# ──────────────────────────────────────────────

@router.get("/{train_session_id}")
def get_train_session(
    train_session_id: int,
    day: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    phone_map = _get_train_phone_map(session, current_user.id, [ts.session_id_1, ts.session_id_2])

    summary = _get_train_summary(session, ts.id)
    total = summary["total"]
    pending = summary["pending"]
    day_summaries = _get_train_day_summaries(session, ts.id)
    available_days = [item["day_number"] for item in day_summaries]
    selected_day = day if day in available_days else (available_days[0] if available_days else None)

    if ts.status == "scheduled" and total > 0 and pending == 0:
        ts.status = "finished"
        session.add(ts)
        session.commit()

    if selected_day is None:
        messages = []
        filtered_total = 0
        total_pages = 1
        page = 1
    else:
        filtered_total = session.exec(
            select(func.count(TrainMessage.id)).where(
                TrainMessage.train_session_id == ts.id,
                TrainMessage.day_number == selected_day,
            )
        ).one()
        total_pages = max((filtered_total + page_size - 1) // page_size, 1)
        page = min(page, total_pages)
        messages = session.exec(
            select(TrainMessage)
            .where(
                TrainMessage.train_session_id == ts.id,
                TrainMessage.day_number == selected_day,
            )
            .order_by(TrainMessage.position.asc(), TrainMessage.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

    return {
        "session": TrainSessionRead(
            **_build_train_session_read(ts, total, phone_map).model_dump()
        ),
        "summary": summary,
        "days": day_summaries,
        "selected_day": selected_day,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "filtered_total": filtered_total,
            "total_pages": total_pages,
        },
        "messages": [
            TrainMessageRead(
                **(
                    _serialize_train_message(m).model_dump()
                    | {
                        "sender_phone_name": (
                            phone_map.get(m.sender_session_id).name
                            if phone_map.get(m.sender_session_id)
                            else None
                        ),
                        "sender_side": 1 if m.sender_session_id == ts.session_id_1 else 2,
                    }
                )
            )
            for m in messages
        ],
    }


# ──────────────────────────────────────────────
# Retry a failed train session
# ──────────────────────────────────────────────

@router.post(
    "/{train_session_id}/retry",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_by_user(3, 60, "train-retry"))],
)
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

    from sqlmodel import delete
    session.exec(
        delete(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    )

    ts.status = "generating"
    ts.error_message = None
    session.add(ts)
    session.commit()

    process_train_session(ts.id, req.model_dump())

    return {"success": True, "train_session_id": ts.id}


# ──────────────────────────────────────────────
# Cancel a train session
# ──────────────────────────────────────────────

@router.post("/{train_session_id}/cancel", dependencies=[Depends(rate_limit_by_user(5, 60, "train-cancel"))])
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
        .where(OutboxMessage.status.in_(["pending", "queued", "paused"]))
        .values(status="cancelled")
    )

    session.exec(
        update(TrainMessage)
        .where(TrainMessage.train_session_id == ts.id)
        .where(TrainMessage.status.in_(["pending", "paused"]))
        .values(status="cancelled", error_message="Train session cancelled")
    )

    session.commit()

    return {"success": True}


@router.post(
    "/{train_session_id}/pause",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_by_user(5, 60, "train-pause"))],
)
def pause_train_session(
    train_session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if ts.status != "scheduled":
        raise HTTPException(status_code=400, detail="Only scheduled train sessions can be paused")

    ts.status = "paused"
    session.add(ts)

    session.exec(
        update(OutboxMessage)
        .where(OutboxMessage.train_id == ts.id)
        .where(OutboxMessage.status.in_(["pending", "queued"]))
        .values(status="paused", leased_until=None)
    )

    session.exec(
        update(TrainMessage)
        .where(TrainMessage.train_session_id == ts.id)
        .where(TrainMessage.status == "pending")
        .values(status="paused", error_message="Train session paused")
    )

    session.commit()

    return {"success": True}


@router.post(
    "/{train_session_id}/resume",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_by_user(5, 60, "train-resume"))],
)
def resume_train_session(
    train_session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ts = session.get(TrainSession, train_session_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Train session not found")
    if ts.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if ts.status != "paused":
        raise HTTPException(status_code=400, detail="Only paused train sessions can be resumed")

    paused_outbox_messages = session.exec(
        select(OutboxMessage)
        .where(OutboxMessage.train_id == ts.id)
        .where(OutboxMessage.status == "paused")
        .order_by(OutboxMessage.scheduled_at.asc(), OutboxMessage.id.asc())
    ).all()
    paused_train_messages = session.exec(
        select(TrainMessage)
        .where(TrainMessage.train_session_id == ts.id)
        .where(TrainMessage.status == "paused")
        .order_by(TrainMessage.scheduled_at.asc(), TrainMessage.id.asc())
    ).all()

    shift_delta = timedelta(0)
    earliest_paused_at = next(
        (msg.scheduled_at for msg in paused_outbox_messages if msg.scheduled_at is not None),
        None,
    )
    if earliest_paused_at is not None:
        now = datetime.now(timezone.utc)
        if earliest_paused_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        resume_anchor = max(now, earliest_paused_at)
        shift_delta = resume_anchor - earliest_paused_at

    ts.status = "scheduled"
    if ts.scheduled_at is not None and shift_delta:
        ts.scheduled_at = ts.scheduled_at + shift_delta
    session.add(ts)

    for outbox_message in paused_outbox_messages:
        outbox_message.status = "pending"
        outbox_message.leased_until = None
        outbox_message.not_before_at = None
        if outbox_message.scheduled_at is not None and shift_delta:
            outbox_message.scheduled_at = outbox_message.scheduled_at + shift_delta
        session.add(outbox_message)

    for train_message in paused_train_messages:
        train_message.status = "pending"
        train_message.error_message = None
        if train_message.scheduled_at is not None and shift_delta:
            train_message.scheduled_at = train_message.scheduled_at + shift_delta
        session.add(train_message)

    session.commit()

    return {"success": True}


# ──────────────────────────────────────────────
# Delete a train session (only if not yet started)
# ──────────────────────────────────────────────

@router.delete(
    "/{train_session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_by_user(5, 60, "train-delete"))],
)
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

    if ts.status in ["scheduled", "paused"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an active or paused train session. Cancel it first."
        )

    from sqlmodel import delete
    session.exec(
        delete(TrainMessage).where(TrainMessage.train_session_id == ts.id)
    )

    session.delete(ts)
    session.commit()
    return None

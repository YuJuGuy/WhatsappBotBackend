from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
import random
import string
import httpx
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from app.schemas.phone import PhoneBase, PhoneInfo, SessionStatusWebhookEvent
from app.schemas.phone import PhoneGroupCreate, PhoneGroupUpdate, PhoneGroupRead
from app.api.deps import get_session, get_current_user, require_feature
from app.core.features import Feature
from app.api.rate_limit import rate_limit_by_user, rate_limit_by_user_and_path
from app.models.phone import Phone, Group, PhoneGroupLink
from app.models.messages import Messages
from app.models.user import User
from fastapi.responses import JSONResponse, Response
from app.utils.waha import get_session_info, get_qr_code, request_code, create_session, start_session, delete_session, restart_session
from dotenv import load_dotenv
import os
load_dotenv()
router = APIRouter(dependencies=[Depends(require_feature(Feature.phones))])

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")


def _waha_result_has_error(result: dict) -> bool:
    status_code = result.get("statusCode")
    if isinstance(status_code, int) and status_code >= 400:
        return True
    return bool(result.get("error"))


# ──────────────────────────────────────────────
# Phone CRUD
# ──────────────────────────────────────────────

def generate_session_id():
    """Generate a unique session ID for each phone"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))


@router.post("/", dependencies=[Depends(rate_limit_by_user(10, 60, "phone-create"))])
def create_phone(
    phone_in: PhoneBase,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new phone"""
    phone_obj = Phone(
        name=phone_in.name,
        description=phone_in.description,
        session_id=generate_session_id(),
        user_id=current_user.id,
        number="",
        status="STOPPED"
    )
    session.add(phone_obj)
    session.commit()
    return {"success": True}


@router.put("/{phone_id}", dependencies=[Depends(rate_limit_by_user(20, 60, "phone-update"))])
def update_phone(
    phone_id: int,
    phone_in: PhoneBase,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update a specific phone by ID"""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone")
    phone.name = phone_in.name
    phone.description = phone_in.description
    session.add(phone)
    session.commit()
    return {"success": True}

@router.get("/", response_model=List[PhoneInfo])
def get_all_phones(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get all phones for the current user"""
    phones = session.exec(select(Phone).where(Phone.user_id == current_user.id)).all()
    return phones


@router.get("/{phone_id}", response_model=PhoneInfo)
def get_phone(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific phone by ID"""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone")
    return phone


@router.delete("/{phone_id}", dependencies=[Depends(rate_limit_by_user(10, 60, "phone-delete"))])
async def delete_phone(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a phone and its WAHA session."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Check if phone is used in any group
    link = session.exec(select(PhoneGroupLink).where(PhoneGroupLink.phone_id == phone_id)).first()
    if link:
        raise HTTPException(status_code=400, detail="الرقم مستخدم في مجموعة، احذفه من المجموعة أولاً")

    # Delete WAHA session — if already gone (404), proceed anyway
    try:
        await delete_session(phone.session_id)
    except httpx.HTTPStatusError as e:
        print(f"WAHA delete HTTPStatusError: {e.response.status_code} - {e.response.text}")
        if e.response.status_code != 404:
            raise HTTPException(status_code=500, detail="فشل حذف الجلسة من WAHA، حاول مرة أخرى")
    except Exception as e:
        print(f"WAHA delete error: {type(e).__name__} - {e}")
        raise HTTPException(status_code=500, detail="فشل حذف الجلسة من WAHA، حاول مرة أخرى")

    from sqlmodel import delete
    session.exec(
        delete(Messages).where(
            Messages.user_id == current_user.id,
            Messages.session_id == phone.session_id,
        )
    )

    session.delete(phone)
    session.commit()
    return {"success": True}


@router.post(
    "/{phone_id}/restart",
    dependencies=[
        Depends(rate_limit_by_user(5, 60, "phone-restart-user")),
        Depends(rate_limit_by_user_and_path(2, 60, "phone-restart", "phone_id")),
    ],
)
async def restart_phone_session(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Restart a phone session — deletes and recreates to get a fresh QR scan."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Restart WAHA session
    try:
        result = await restart_session(phone.session_id)
        waha_status = result.get("status", "STARTING")
    except Exception:
        raise HTTPException(status_code=500, detail="فشل إعادة تشغيل الجلسة")

    # Map WAHA status directly
    phone.status = waha_status

    session.add(phone)
    session.commit()
    session.refresh(phone)

    return {
        "status": phone.status,
        "waha_status": waha_status,
        "number": phone.number
    }


@router.post(
    "/{phone_id}/start",
    dependencies=[
        Depends(rate_limit_by_user(5, 60, "phone-start-user")),
        Depends(rate_limit_by_user_and_path(2, 60, "phone-start", "phone_id")),
    ],
)
async def start_phone_session(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Start or recreate a phone session explicitly."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        info = await get_session_info(phone.session_id)
        current_status = info.get("status", "STOPPED")
    except Exception:
        info = {}
        current_status = "STOPPED"

    try:
        if current_status == "STOPPED":
            result = {}
            try:
                result = await start_session(phone.session_id)
            except Exception:
                result = {}

            if _waha_result_has_error(result):
                result = await create_session(
                    phone.session_id,
                    webhook_url=f"{WEBHOOK_BASE_URL}/api/webhook" if WEBHOOK_BASE_URL else "",
                    user_id=phone.user_id,
                )
        else:
            result = await restart_session(phone.session_id)
            if _waha_result_has_error(result):
                raise HTTPException(status_code=500, detail="Failed to restart session")
        waha_status = result.get("status", "STARTING")
        info = result
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to start session")

    phone.status = waha_status
    if waha_status == "WORKING":
        me = info.get("me", {})
        if me and me.get("id"):
            phone.number = me["id"].split("@")[0]

    session.add(phone)
    session.commit()
    session.refresh(phone)

    return {
        "status": phone.status,
        "waha_status": waha_status,
        "number": phone.number
    }


# ──────────────────────────────────────────────
# Session Status & QR Code 
# ──────────────────────────────────────────────

@router.get("/{phone_id}/status")
async def check_phone_status(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Check WAHA session status for a phone. Updates DB status accordingly."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        info = await get_session_info(phone.session_id)
        waha_status = info.get("status", "STOPPED")
    except Exception:
        waha_status = "STOPPED"
        info = {}

    # Map WAHA status to our DB status
    # Map WAHA status directly
    phone.status = waha_status
    if waha_status == "WORKING":
        # Try to get the phone number from the session info
        me = info.get("me", {})
        if me and me.get("id"):
            # id format is "1234567890@c.us"
            phone.number = me["id"].split("@")[0]

    session.add(phone)
    session.commit()
    session.refresh(phone)

    return {
        "status": phone.status,
        "waha_status": waha_status,
        "number": phone.number
    }


@router.get("/{phone_id}/qr")
async def get_phone_qr(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get QR code image for pairing a phone session."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        qr_bytes = await get_qr_code(phone.session_id)
        return Response(content=qr_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get QR code: {str(e)}")


@router.post(
    "/{phone_id}/request-code",
    dependencies=[
        Depends(rate_limit_by_user(5, 60, "phone-request-code-user")),
        Depends(rate_limit_by_user_and_path(2, 60, "phone-request-code", "phone_id")),
    ],
)
async def phone_request_code(
    phone_id: int,
    body: dict = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Request pairing code via phone number."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Use phone_number from body if provided, otherwise fallback to phone.number
    phone_number = (body or {}).get("phone_number") or phone.number
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required")

    result = await request_code(phone.session_id, phone_number)
    return result


# ──────────────────────────────────────────────
# Phone Group CRUD
# ──────────────────────────────────────────────

def _build_group_response(group: Group) -> dict:
    """Build a response dict with nested phones."""
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "phones": [
            {
                "id": link.phone.id,
                "name": link.phone.name,
                "description": link.phone.description,
                "status": link.phone.status,
                "session_id": link.phone.session_id,
                "number": link.phone.number,
            }
            for link in group.phone_links
        ]
    }


def _sync_phone_links(
    session: Session,
    group: Group,
    phone_ids: List[int],
    current_user_id: int
):
    """Replace all phone links in a group with the given phone_ids."""
    # Delete existing links
    existing_links = session.exec(
        select(PhoneGroupLink).where(PhoneGroupLink.group_id == group.id)
    ).all()
    for link in existing_links:
        session.delete(link)

    # Create new links
    for pid in phone_ids:
        phone = session.get(Phone, pid)
        if not phone or phone.user_id != current_user_id:
            raise HTTPException(
                status_code=400,
                detail=f"Phone with id {pid} not found or not owned by you"
            )
        link = PhoneGroupLink(
            phone_id=pid,
            group_id=group.id,
        )
        session.add(link)


@router.post(
    "/groups/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_by_user(10, 60, "phone-group-create"))],
)
def create_phone_group(
    group_in: PhoneGroupCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new phone group, optionally linking phones by ID."""
    group = Group(
        name=group_in.name,
        description=group_in.description,
        user_id=current_user.id
    )
    session.add(group)
    session.commit()
    session.refresh(group)

    if group_in.phone_ids:
        _sync_phone_links(session, group, group_in.phone_ids, current_user.id)
        session.commit()

    return {"success": True}


@router.get("/groups/", response_model=List[PhoneGroupRead])
def get_phone_groups(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all phone groups for the current user, with nested phones."""
    groups = session.exec(
        select(Group)
        .where(Group.user_id == current_user.id)
        .options(selectinload(Group.phone_links).selectinload(PhoneGroupLink.phone))
    ).all()
    return [_build_group_response(g) for g in groups]


@router.get("/groups/{group_id}", response_model=PhoneGroupRead)
def get_phone_group(
    group_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single phone group by ID with nested phones."""
    group = session.exec(
        select(Group)
        .where(Group.id == group_id)
        .options(selectinload(Group.phone_links).selectinload(PhoneGroupLink.phone))
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="Phone group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone group")
    return _build_group_response(group)


@router.put("/groups/{group_id}", dependencies=[Depends(rate_limit_by_user(10, 60, "phone-group-update"))])
def update_phone_group(
    group_id: int,
    group_in: PhoneGroupUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update a phone group — name, description, and/or phone list."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Phone group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone group")

    if group_in.name is not None:
        group.name = group_in.name
    if group_in.description is not None:
        group.description = group_in.description

    session.add(group)
    session.commit()

    if group_in.phone_ids is not None:
        _sync_phone_links(session, group, group_in.phone_ids, current_user.id)
        session.commit()

    return {"success": True}


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_by_user(10, 60, "phone-group-delete"))],
)
def delete_phone_group(
    group_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a phone group. Only removes the group and links, not the phones themselves."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Phone group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone group")

    # Delete links first
    links = session.exec(
        select(PhoneGroupLink).where(PhoneGroupLink.group_id == group.id)
    ).all()
    for link in links:
        session.delete(link)

    session.delete(group)
    session.commit()
    return None


# ──────────────────────────────────────────────
# Webhook
# ──────────────────────────────────────────────

async def session_status_webhook(event: SessionStatusWebhookEvent):
    """Handle session.status webhook from WAHA with security checks."""
    session_id = event.session
    waha_status = event.payload.status
    user_id = event.user_id
    if not session_id or not waha_status:
        return

    db_generator = get_session()
    db = next(db_generator)
    try:
        phone = db.exec(select(Phone).where(Phone.session_id == session_id)).first()
        if not phone:
            print(f"[Webhook] Phone not found for session_status: {session_id}")
            return

        # Security Check 1: Verify the webhook came from the correct user session
        if user_id is not None and phone.user_id != user_id:
            print(f"[Webhook] User ID mismatch for session {session_id}. Expected {phone.user_id}, got {user_id}")
            return

        # Security Check 2: If connected, verify the phone number isn't hijacked
        if waha_status == "WORKING":
            try:
                # Get the connected number directly from the webhook payload!
                if event.me and event.me.id:
                    connected_number = event.me.id.split("@")[0]
                    
                    # Check if this number is already registered to a DIFFERENT user
                    existing_phone = db.exec(
                        select(Phone).where(Phone.number == connected_number, Phone.user_id != phone.user_id)
                    ).first()
                    
                    if existing_phone:
                        print(f"[Webhook] Security: Number {connected_number} is already registered to another user!")
                        from app.utils.waha import delete_session
                        await delete_session(session_id)
                        phone.status = "failed"
                        phone.description = "فشل الربط: الرقم مستخدم من قبل حساب آخر"
                        db.add(phone)
                        db.commit()
                        return

                    # Update the number if it's new
                    if phone.number != connected_number:
                        phone.number = connected_number
            except Exception as e:
                print(f"[Webhook] Failed to get session info for {session_id}: {e}")

        # Map WAHA status directly
        phone.status = waha_status

        db.add(phone)
        db.commit()
        print(f"[Webhook] Updated phone {phone.id} status to {phone.status} (waha: {waha_status})")
    finally:
        db.close()

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
import random
import string
import httpx
from sqlmodel import Session, select
from app.schemas.phone import PhoneBase, PhoneInfo
from app.schemas.phone import PhoneGroupCreate, PhoneGroupUpdate, PhoneGroupRead
from app.api.deps import get_session, get_current_user
from app.models.phone import Phone, Group, PhoneGroupLink
from app.models.user import User
from fastapi.responses import JSONResponse, Response
from app.utils.waha import get_session_info, get_qr_code, request_code, create_session, start_session, delete_session, restart_session
from dotenv import load_dotenv
import os
load_dotenv()
router = APIRouter()

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")


# ──────────────────────────────────────────────
# Phone CRUD
# ──────────────────────────────────────────────

def generate_session_id():
    """Generate a unique session ID for each phone"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))


@router.post("/", response_model=PhoneInfo)
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
        status="pending"
    )
    session.add(phone_obj)
    session.commit()
    session.refresh(phone_obj)
    return JSONResponse(status_code=201, content="Phone created successfully")


@router.put("/{phone_id}", response_model=PhoneInfo)
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
    session.refresh(phone)
    return phone

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


@router.delete("/{phone_id}")
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

    session.delete(phone)
    session.commit()
    return {"detail": "Phone deleted"}


@router.post("/{phone_id}/restart")
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

    if waha_status == "SCAN_QR_CODE":
        phone.status = "scan_qr"
    elif waha_status == "WORKING":
        phone.status = "connected"
    else:
        phone.status = "starting"

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

    # If session doesn't exist or is stopped, create it
    if waha_status == "STOPPED":
        try:
            create_result = await create_session(
                phone.session_id, 
                webhook_url=f"{WEBHOOK_BASE_URL}/api/webhook" if WEBHOOK_BASE_URL else "",
                user_id=phone.user_id
            )
            waha_status = create_result.get("status", "STARTING")
            info = create_result
        except Exception:
            waha_status = "STARTING"

    # Map WAHA status to our DB status
    if waha_status == "WORKING":
        phone.status = "connected"
        # Try to get the phone number from the session info
        me = info.get("me", {})
        if me and me.get("id"):
            # id format is "1234567890@c.us"
            phone.number = me["id"].split("@")[0]
    elif waha_status == "SCAN_QR_CODE":
        phone.status = "scan_qr"
    elif waha_status == "STARTING":
        phone.status = "starting"
    elif waha_status == "FAILED":
        phone.status = "failed"
    else:
        phone.status = "pending"

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


@router.post("/{phone_id}/request-code")
async def phone_request_code(
    phone_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Request pairing code via phone number."""
    phone = session.get(Phone, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    if phone.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not phone.number:
        raise HTTPException(status_code=400, detail="Phone number is not set")

    result = await request_code(phone.session_id, phone.number)
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


@router.post("/groups/", response_model=PhoneGroupRead, status_code=status.HTTP_201_CREATED)
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
        session.refresh(group)

    return _build_group_response(group)


@router.get("/groups/", response_model=List[PhoneGroupRead])
def get_phone_groups(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all phone groups for the current user, with nested phones."""
    groups = session.exec(
        select(Group).where(Group.user_id == current_user.id)
    ).all()
    return [_build_group_response(g) for g in groups]


@router.get("/groups/{group_id}", response_model=PhoneGroupRead)
def get_phone_group(
    group_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single phone group by ID with nested phones."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Phone group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this phone group")
    return _build_group_response(group)


@router.put("/groups/{group_id}", response_model=PhoneGroupRead)
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

    session.refresh(group)
    return _build_group_response(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
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

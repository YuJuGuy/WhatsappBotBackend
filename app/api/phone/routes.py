from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
import random
import string
from sqlmodel import Session, select
from app.schemas.phone import PhoneBase, PhoneInfo
from app.api.deps import get_session, get_current_user
from app.models.phone import Phone
from app.models.user import User
from fastapi.responses import JSONResponse

router = APIRouter()


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

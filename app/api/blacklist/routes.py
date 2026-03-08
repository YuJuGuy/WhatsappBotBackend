from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.blacklist import BlacklistRead, BlacklistCreate
from app.api.deps import get_session, get_current_user
from app.models.blacklist import Blacklist
from app.models.user import User
from sqlmodel import Session, select

router = APIRouter()


@router.post("/", response_model=BlacklistRead, status_code=status.HTTP_201_CREATED)
def create_blacklist(
    blacklist_in: BlacklistCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new blacklist entry"""

    existing_stmt = select(Blacklist).where(
        Blacklist.user_id == current_user.id,
        Blacklist.phone_number == blacklist_in.phone_number
    )
    existing = session.exec(existing_stmt).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is already blacklisted"
        )

    blacklist_obj = Blacklist(
        phone_number=blacklist_in.phone_number,
        user_id=current_user.id
    )
    session.add(blacklist_obj)
    session.commit()
    session.refresh(blacklist_obj)
    return blacklist_obj


@router.get("/", response_model=list[BlacklistRead])
def get_blacklist(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get all blacklist entries for the current user"""
    stmt = select(Blacklist).where(Blacklist.user_id == current_user.id)
    results = session.exec(stmt).all()
    return results


@router.delete("/{blacklist_id}", response_model=BlacklistRead)
def delete_blacklist(
    blacklist_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a blacklist entry"""
    stmt = select(Blacklist).where(
        Blacklist.id == blacklist_id,
        Blacklist.user_id == current_user.id
    )
    blacklist_obj = session.exec(stmt).first()

    if not blacklist_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blacklist entry not found"
        )

    session.delete(blacklist_obj)
    session.commit()
    return blacklist_obj
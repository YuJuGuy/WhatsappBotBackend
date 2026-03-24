from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlmodel import Session, select

from app.api.deps import get_current_superuser, get_current_user, get_session
from app.core.features import Feature, expand_features
from app.core.security import get_password_hash
from app.models.outbox import OutboxMessage
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserUpdate, UserRead
from app.api.rate_limit import rate_limit_by_user

router = APIRouter()


def _effective_features(user: User) -> set[Feature]:
    if user.is_superuser:
        return set(Feature)
    return set(expand_features(user.allowed_features or []))


def _cancel_removed_feature_outbox(
    session: Session,
    user_id: int,
    removed_features: set[Feature],
):
    if not removed_features:
        return

    session.exec(
        update(OutboxMessage)
        .where(
            OutboxMessage.user_id == user_id,
            OutboxMessage.source_feature.in_([feature.value for feature in removed_features]),
            OutboxMessage.status.in_(["pending", "queued"]),
        )
        .values(
            status="cancelled",
            leased_until=None,
            not_before_at=None,
        )
    )

@router.get("/me", response_model=UserRead)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_session),
    _: User = Depends(get_current_superuser),
):
    return session.exec(select(User).order_by(User.id.asc())).all()


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_by_user(10, 60, "users-create"))],
)
def create_user(
    user_in: AdminUserCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_superuser),
):
    existing_user = session.exec(select(User).where(User.email == user_in.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    allowed_features = [] if user_in.is_superuser else expand_features(user_in.allowed_features)

    user = User(
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        is_active=user_in.is_active,
        is_superuser=user_in.is_superuser,
        full_name=user_in.full_name,
        expiry_date=user_in.expiry_date,
        allowed_features=allowed_features,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.put(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(rate_limit_by_user(20, 60, "users-update"))],
)
def update_user(
    user_id: int,
    user_in: AdminUserUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_superuser),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_features = _effective_features(user)
    update_data = user_in.model_dump(exclude_unset=True)

    new_email = update_data.get("email")
    if new_email is not None and new_email != user.email:
        existing_user = session.exec(select(User).where(User.email == new_email)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = new_email

    if "is_active" in update_data:
        user.is_active = update_data["is_active"]
    if "is_superuser" in update_data:
        if user.id == current_user.id and not update_data["is_superuser"]:
            raise HTTPException(status_code=400, detail="You cannot remove your own admin access")
        user.is_superuser = update_data["is_superuser"]
    if "full_name" in update_data:
        user.full_name = update_data["full_name"]
    if "expiry_date" in update_data:
        user.expiry_date = update_data["expiry_date"]
    if "allowed_features" in update_data:
        user.allowed_features = expand_features(update_data["allowed_features"])
    if user.is_superuser:
        user.allowed_features = []

    removed_features = previous_features - _effective_features(user)
    _cancel_removed_feature_outbox(session, user.id, removed_features)

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_by_user(10, 60, "users-delete"))],
)
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_superuser),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    session.delete(user)
    session.commit()
    return None

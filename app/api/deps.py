from datetime import date
from typing import Annotated
from fastapi import Depends, HTTPException, status
from jose import jwt, JWTError
from sqlmodel import Session
from app.core.config import settings
from app.core.features import Feature, expand_features
from app.db.engine import get_session
from app.models.user import User
from app.schemas.token import TokenData


def _error_detail(code: str, message: str, **extra):
    detail = {"code": code, "message": message}
    detail.update(extra)
    return detail


def ensure_user_can_access(user: User) -> User:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_detail("ACCOUNT_INACTIVE", "Inactive user"),
        )
    if user.expiry_date and user.expiry_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_detail("ACCOUNT_EXPIRED", "User account has expired"),
        )
    return user


def user_has_feature(user: User, feature: Feature | str) -> bool:
    try:
        ensure_user_can_access(user)
    except HTTPException:
        return False

    if user.is_superuser:
        return True

    feature_name = feature.value if isinstance(feature, Feature) else str(feature)
    allowed_features = user.allowed_features or []
    normalized = {item.value for item in expand_features(allowed_features)}
    return feature_name in normalized

from fastapi import Request

def get_current_user(request: Request, session: Session = Depends(get_session)):
    token = request.cookies.get("access_token")

    # fallback to Authorization header for API clients
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        print("DECODED PAYLOAD:", payload)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    except JWTError as e:
        print("JWT DECODE ERROR:", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = session.get(User, int(user_id))

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return ensure_user_can_access(user)


def get_current_superuser(current_user: User = Depends(get_current_user)):
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_detail("SUPERUSER_REQUIRED", "Not enough permissions"),
        )
    return current_user


def require_feature(feature: Feature | str):
    feature_name = feature.value if isinstance(feature, Feature) else str(feature)

    def dependency(current_user: User = Depends(get_current_user)):
        if not user_has_feature(current_user, feature_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_error_detail(
                    "FEATURE_NOT_ALLOWED",
                    "You do not have access to this feature.",
                    feature=feature_name,
                ),
            )

        return current_user

    return dependency

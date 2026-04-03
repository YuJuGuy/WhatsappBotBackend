from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
from sqlmodel import Session, select
from app.api.deps import ensure_user_can_access, get_session
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_password, hash_token
from app.models.user import User
from app.models.refresh_token import RefreshToken
from datetime import datetime, timedelta, timezone
from app.schemas.token import Token
from app.schemas.user import UserLogin
from app.api.rate_limit import rate_limit_by_ip
import os
from dotenv import load_dotenv
load_dotenv()

router = APIRouter()

@router.post("/login", dependencies=[Depends(rate_limit_by_ip(5, 60, "auth-login"))])
def login(response: Response, form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: Session = Depends(get_session)):
    # Note: OAuth2PasswordRequestForm expects username field, so client should send username=email
    user = session.exec(select(User).where(User.email == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    ensure_user_can_access(user)
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

    token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=expires_at
    )

    session.add(token_record)

    # limit sessions per user (max 5)
    user_tokens = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False
        )
    ).all()

    if len(user_tokens) > 5:
        oldest = sorted(user_tokens, key=lambda t: t.created_at)[0]
        oldest.revoked = True
        session.add(oldest)

    session.commit()

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True if os.getenv("ENV") == "prod" else False,
        samesite="none" if os.getenv("ENV") == "prod" else "lax",
        domain=os.getenv("COOKIE_DOMAIN") if os.getenv("ENV") == "prod" else None,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True if os.getenv("ENV") == "prod" else False,
        samesite="none" if os.getenv("ENV") == "prod" else "lax",
        domain=os.getenv("COOKIE_DOMAIN") if os.getenv("ENV") == "prod" else None,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )

    return {"message": "Login successful"}

@router.post("/logout")
def logout(response: Response, request: Request, session: Session = Depends(get_session)):
    refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        token_hash = hash_token(refresh_token)

        token_record = session.exec(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False
            )
        ).first()

        if token_record:
            token_record.revoked = True
            session.add(token_record)
            session.commit()

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")

    return {"message": "Logged out"}


@router.post("/refresh", dependencies=[Depends(rate_limit_by_ip(20, 60, "auth-refresh"))])
def refresh_token(request: Request, response: Response, session: Session = Depends(get_session)):
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if user_id is None or token_type != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = session.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    ensure_user_can_access(user)

    token_hash = hash_token(refresh_token)

    token_record = session.exec(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False
        )
    ).first()

    if not token_record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    token_record.revoked = True
    session.add(token_record)

    new_refresh_token = create_refresh_token(subject=user.id)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

    new_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh_token),
        expires_at=expires_at
    )

    session.add(new_record)

    access_token = create_access_token(subject=user.id)

    session.commit()

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True if os.getenv("ENV") == "prod" else False,
        samesite="none" if os.getenv("ENV") == "prod" else "lax",
        domain=os.getenv("COOKIE_DOMAIN") if os.getenv("ENV") == "prod" else None,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )

    return {"message": "Token refreshed"}

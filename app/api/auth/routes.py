from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
from sqlmodel import Session, select
from app.api.deps import ensure_user_can_access, get_session
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_password
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import UserLogin
from app.api.rate_limit import rate_limit_by_ip

router = APIRouter()

@router.post("/login", response_model=Token, dependencies=[Depends(rate_limit_by_ip(5, 60, "auth-login"))])
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: Session = Depends(get_session)):
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
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

# Custom login endpoint if not using OAuth2 form data
@router.post("/login/json", response_model=Token, dependencies=[Depends(rate_limit_by_ip(5, 60, "auth-login-json"))])
def login_json(user_in: UserLogin, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == user_in.email)).first()
    if not user or not verify_password(user_in.password, user.password_hash):
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    ensure_user_can_access(user)
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

@router.post("/refresh", response_model=Token, dependencies=[Depends(rate_limit_by_ip(20, 60, "auth-refresh"))])
def refresh_token(refresh_token: str, session: Session = Depends(get_session)):
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
        
    access_token = create_access_token(subject=user.id)
    # Optionally rotate refresh token here
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

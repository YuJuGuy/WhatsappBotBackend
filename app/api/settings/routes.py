from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.api.deps import get_session, get_current_user
from app.models.settings import Settings
from app.models.user import User



router = APIRouter()



@router.get("/", response_model=list[SettingsRead])
def get_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get all settings for the current user"""
    settings = session.exec(select(Settings).where(Settings.user_id == current_user.id)).all()
    return settings


@router.put("/" , response_model=SettingsRead)
def update_settings(
    settings_in: SettingsUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update settings for the current user"""
    settings = session.exec(select(Settings).where(Settings.user_id == current_user.id)).first()
    if not settings:
        settings = Settings(user_id=current_user.id)
    settings.delay = settings_in.delay
    settings.min_delay_seconds = settings_in.min_delay_seconds
    settings.max_delay_seconds = settings_in.max_delay_seconds
    settings.sleep = settings_in.sleep
    settings.sleep_after_messages = settings_in.sleep_after_messages
    settings.min_sleep_seconds = settings_in.min_sleep_seconds
    settings.max_sleep_seconds = settings_in.max_sleep_seconds
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings
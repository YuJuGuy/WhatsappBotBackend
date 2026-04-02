from sqlalchemy import case, func
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_session
from app.models.campaign import Campaign, CampaignRecipient
from app.models.messages import Messages
from app.models.outbox import OutboxMessage
from app.models.phone import Phone
from app.models.train import TrainMessage, TrainSession
from app.models.user import User
from app.schemas.dashboard import DashboardRecentItem, DashboardSummaryRead


router = APIRouter()


@router.get("/summary", response_model=DashboardSummaryRead)
def get_dashboard_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    phone_counts = session.exec(
        select(
            func.count(Phone.id),
            func.sum(case((Phone.status == "WORKING", 1), else_=0)),
        ).where(Phone.user_id == current_user.id)
    ).one()
    phones_total = phone_counts[0] or 0
    phones_working = phone_counts[1] or 0

    message_counts = session.exec(
        select(
            func.sum(case((Messages.from_me.is_(True), 1), else_=0)),
            func.sum(case((Messages.from_me.is_(False), 1), else_=0)),
        ).where(Messages.user_id == current_user.id)
    ).one()
    messages_sent = message_counts[0] or 0
    messages_received = message_counts[1] or 0

    outbox_counts = session.exec(
        select(
            func.sum(case((OutboxMessage.status.in_(["pending", "queued", "paused"]), 1), else_=0)),
            func.sum(case((OutboxMessage.status == "failed", 1), else_=0)),
        ).where(OutboxMessage.user_id == current_user.id)
    ).one()
    sends_pending = outbox_counts[0] or 0
    sends_failed = outbox_counts[1] or 0

    campaigns_active = session.exec(
        select(func.count(Campaign.id)).where(
            Campaign.user_id == current_user.id,
            Campaign.status == "scheduled",
        )
    ).one()

    train_active = session.exec(
        select(func.count(TrainSession.id)).where(
            TrainSession.user_id == current_user.id,
            TrainSession.status.in_(["scheduled", "paused", "generated", "generating"]),
        )
    ).one()

    latest_campaign_row = session.exec(
        select(
            Campaign.id,
            Campaign.name,
            Campaign.status,
            Campaign.created_at,
            func.count(CampaignRecipient.id),
        )
        .outerjoin(CampaignRecipient, CampaignRecipient.campaign_id == Campaign.id)
        .where(Campaign.user_id == current_user.id)
        .group_by(Campaign.id)
        .order_by(Campaign.created_at.desc())
        .limit(1)
    ).first()

    latest_train_row = session.exec(
        select(
            TrainSession.id,
            TrainSession.name,
            TrainSession.status,
            TrainSession.created_at,
            func.count(TrainMessage.id),
        )
        .outerjoin(TrainMessage, TrainMessage.train_session_id == TrainSession.id)
        .where(TrainSession.user_id == current_user.id)
        .group_by(TrainSession.id)
        .order_by(TrainSession.created_at.desc())
        .limit(1)
    ).first()

    latest_campaign = (
        DashboardRecentItem(
            id=latest_campaign_row[0],
            name=latest_campaign_row[1],
            status=latest_campaign_row[2],
            created_at=latest_campaign_row[3],
            detail_count=latest_campaign_row[4] or 0,
        )
        if latest_campaign_row
        else None
    )

    latest_train = (
        DashboardRecentItem(
            id=latest_train_row[0],
            name=latest_train_row[1],
            status=latest_train_row[2],
            created_at=latest_train_row[3],
            detail_count=latest_train_row[4] or 0,
        )
        if latest_train_row
        else None
    )

    return DashboardSummaryRead(
        phones_total=phones_total,
        phones_working=phones_working,
        messages_sent=messages_sent,
        messages_received=messages_received,
        sends_pending=sends_pending,
        sends_failed=sends_failed,
        campaigns_active=campaigns_active or 0,
        train_active=train_active or 0,
        latest_campaign=latest_campaign,
        latest_train=latest_train,
    )

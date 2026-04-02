from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.api.deps import user_has_feature
from app.core.features import Feature
from app.db.engine import engine
from app.models.user import User
from app.models.phone import Phone
from app.utils.hmac_verify import verify_webhook_hmac
from app.schemas.call import CallWebhookEvent
from app.api.calls.routes import call_webhook
from app.schemas.messages import MessageWebhookEvent
from app.api.messages.routes import save_message
from app.api.autoreply.routes import message_webhook
from app.api.phone.routes import session_status_webhook
from app.schemas.phone import SessionStatusWebhookEvent
from app.api.flow.routes import webhook_flow_executor

router = APIRouter()


def _get_webhook_user(user_id: str | None) -> User | None:
    if not user_id:
        return None

    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    with Session(engine) as session:
        return session.get(User, parsed_user_id)


@router.post("/", dependencies=[Depends(verify_webhook_hmac)])
async def global_webhook_receive(request: Request):
    """
    Global webhook receiver for all WAHA events.
    Accepts raw JSON, dispatches to the correct handler based on event type.
    """
    body = await request.json()
    event_type = body.get("event", "")
    session_id = body.get("session", "")
    user_id = request.headers.get("x-user-id")

    print(f"[Webhook] Received event: {event_type}, session: {session_id}, user_id: {user_id}")

    if event_type == "call.received":
        user = _get_webhook_user(user_id)
        if not user or not user_has_feature(user, Feature.calls):
            return {"status": "ignored", "reason": "calls feature disabled"}

        # Parse into the call-specific schema
        event = CallWebhookEvent(**body)
        await call_webhook(event)

    elif event_type == "message.any":
        # Parse into the message-specific schema
        
        # Fast exit for groups/channels/statuses before any DB or deeper logic parsing
        raw_from = body.get("payload", {}).get("from", "")
        raw_to = body.get("payload", {}).get("to", "")
        
        if (raw_from.endswith("@g.us") or raw_from.endswith("@newsletter") or raw_from == "status@broadcast" or
            (raw_to and (raw_to.endswith("@g.us") or raw_to.endswith("@newsletter") or raw_to == "status@broadcast"))):
            print(f"[Webhook] Early skip for group/channel/status message")
            return {"status": "ignored", "reason": "unsupported chat type"}

        user = _get_webhook_user(user_id)
        
        # Sandbox fallback: resolve user from the phone session if x-user-id is missing
        if not user and request.headers.get("x-sandbox-test") == "true":
            with Session(engine) as s:
                phone = s.exec(select(Phone).where(Phone.session_id == session_id)).first()
                if phone:
                    user = s.get(User, phone.user_id)
        
        if not user:
            return {"status": "ignored", "reason": "invalid user"}

        should_save_message = user_has_feature(user, Feature.messages) or user_has_feature(user, Feature.auto_reply) or user_has_feature(user, Feature.flows)
        should_process_auto_reply = user_has_feature(user, Feature.auto_reply)
        should_process_flows = user_has_feature(user, Feature.flows)

        if not should_save_message and not should_process_auto_reply and not should_process_flows:
            return {"status": "ignored", "reason": "message features disabled"}
            
        event = MessageWebhookEvent(**body, user_id=user.id)
        is_sandbox = (raw_from == "1123456789" or raw_to == "1123456789")
        
        inserted = True
        if should_save_message and not is_sandbox:
            print(f"[Webhook] Saving message")
            _, inserted = save_message(event)
        
        # 2. Process logic only once for a newly saved message (Incoming only)
        sandbox_responses = []
        if (inserted or is_sandbox) and not event.payload.fromMe:
            consumed_by_flow = False
            
            # De-mask the device specific LID identifier to the real phone number.
            cleaned_from = raw_from
            if raw_from.endswith("@lid") and getattr(event.payload, "_data", None):
                if isinstance(event.payload._data, dict):
                    info = event.payload._data.get("Info", {})
                    sender_alt = info.get("SenderAlt", "")
                    if sender_alt and not sender_alt.endswith("@lid"):
                        cleaned_from = sender_alt
                    else:
                        chat = info.get("Chat", "")
                        if chat and not chat.endswith("@lid"):
                            cleaned_from = chat
                            
            cleaned_from = cleaned_from.split(":")[0].split("@")[0]
            
            # 2a. Attempt Visual Flows Execution Engine First!
            if should_process_flows:
                consumed_by_flow, flow_resp = await webhook_flow_executor(
                    incoming_message_id=event.payload.id,
                    session_id=session_id,
                    contact_id=cleaned_from,
                    user_id=user.id,
                    text=event.payload.body or "",
                    is_sandbox=is_sandbox
                )
                if is_sandbox:
                    sandbox_responses.extend(flow_resp)
            
            # 2b. Attempt Standard Keyword Auto-Reply if Flow Engine didn't hijack it!
            if should_process_auto_reply and not consumed_by_flow:
                ar_resp = await message_webhook(event, is_sandbox=is_sandbox)
                if is_sandbox and ar_resp:
                    sandbox_responses.append(ar_resp)
                
        elif not inserted:
            print(f"[Webhook] Skipping processing for duplicate message: {event.payload.id}")
            
        if is_sandbox:
            return {"status": "sandbox", "responses": sandbox_responses}

    elif event_type == "session.status":
        try:
            parsed_user_id = int(user_id) if user_id else None
        except ValueError:
            parsed_user_id = None
            
        event = SessionStatusWebhookEvent(**body, user_id=parsed_user_id)
        await session_status_webhook(event)

    else:
        print(f"[Webhook] Unhandled event type: {event_type}")

    return {"status": "ok"}

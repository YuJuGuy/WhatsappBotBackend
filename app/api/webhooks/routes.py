from fastapi import APIRouter, Depends, Request

from app.utils.hmac_verify import verify_webhook_hmac
from app.schemas.call import CallWebhookEvent
from app.api.calls.routes import call_webhook
from app.schemas.messages import MessageWebhookEvent
from app.api.autoreply.routes import message_webhook, save_message

router = APIRouter()


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
        # Parse into the call-specific schema
        event = CallWebhookEvent(**body)
        await call_webhook(event)

    elif event_type == "message.any":
        # Parse into the message-specific schema
        print(body)
        
        # Fast exit for groups/channels/statuses before any DB or deeper logic parsing
        raw_from = body.get("payload", {}).get("from", "")
        raw_to = body.get("payload", {}).get("to", "")
        
        if (raw_from.endswith("@g.us") or raw_from.endswith("@newsletter") or raw_from == "status@broadcast" or
            (raw_to and (raw_to.endswith("@g.us") or raw_to.endswith("@newsletter") or raw_to == "status@broadcast"))):
            print(f"[Webhook] Early skip for group/channel/status message")
            return {"status": "ignored", "reason": "unsupported chat type"}

        try:
            parsed_user_id = int(user_id) if user_id else None
        except ValueError:
            parsed_user_id = None
            
        event = MessageWebhookEvent(**body, user_id=parsed_user_id)
        
        # 1. Save the incoming message to DB
        save_message(event)
        
        # 2. Process auto-reply logic
        await message_webhook(event)

    else:
        print(f"[Webhook] Unhandled event type: {event_type}")

    return {"status": "ok"}
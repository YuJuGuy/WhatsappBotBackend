"""
HMAC verification for WAHA webhook requests.
Use as a FastAPI dependency to verify incoming webhooks are authentic.
"""
import os
import hmac
import hashlib
from fastapi import Request, HTTPException
from dotenv import load_dotenv

load_dotenv()

WAHA_HMAC_SECRET = os.getenv("WAHA_HMAC_SECRET", "")


async def verify_webhook_hmac(request: Request):
    """
    FastAPI dependency that verifies the HMAC signature of incoming webhooks.
    WAHA sends the signature in the X-Webhook-Hmac-SHA512 header.
    """
    if not WAHA_HMAC_SECRET:
        # HMAC not configured, skip verification
        return

    # WAHA sends signature in x-webhook-hmac (and sometimes X-Webhook-Hmac-SHA512 in older versions?)
    signature = request.headers.get("x-webhook-hmac") or request.headers.get("X-Webhook-Hmac-SHA512")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing HMAC signature")

    body = await request.body()
    expected = hmac.new(
        WAHA_HMAC_SECRET.encode(),
        body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

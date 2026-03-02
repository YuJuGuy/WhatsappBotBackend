"""
Centralized WAHA (WhatsApp HTTP API) client.
All calls to the WAHA service go through here.
"""
import os
import httpx
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://localhost:3000")
API_KEY = os.getenv("API_KEY", "")

_headers = {"X-Api-Key": API_KEY}


# ──────────────────────────────────────────────
# Sessions
# ──────────────────────────────────────────────

WAHA_HMAC_SECRET = os.getenv("WAHA_HMAC_SECRET", "")


async def create_session(name: str, webhook_url: str = "", user_id: Optional[int] = None) -> dict:
    """Create a new WAHA session with webhook config and start it."""
    body: dict = {"name": name, "start": True}
    if webhook_url:
        webhook_cfg: dict = {
            "url": webhook_url,
            "events": ["session.status", "call.received", "message.any"],
        }
        if WAHA_HMAC_SECRET:
            webhook_cfg["hmac"] = {"key": WAHA_HMAC_SECRET}
        if user_id is not None:
            webhook_cfg["customHeaders"] = [
                {
                    "name": "X-User-ID",
                    "value": str(user_id)
                }
            ]
        body["config"] = {"webhooks": [webhook_cfg]}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{WAHA_BASE_URL}/api/sessions",
                json=body,
                headers=_headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise e


async def start_session(name: str) -> dict:
    """Start an existing stopped session."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{WAHA_BASE_URL}/api/sessions/{name}/start",
            headers=_headers
        )
        return response.json()


async def restart_session(name: str) -> dict:
    """Restart a session."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{WAHA_BASE_URL}/api/sessions/{name}/restart",
            headers=_headers
        )
        return response.json()


async def get_session_info(name: str) -> dict:
    """Get information about a session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{WAHA_BASE_URL}/api/sessions/{name}", headers=_headers)
        return response.json()


async def delete_session(name: str):
    """Delete a session. Raises on failure."""
    async with httpx.AsyncClient() as client:
        response = await client.delete(f"{WAHA_BASE_URL}/api/sessions/{name}", headers=_headers)
        response.raise_for_status()


# ──────────────────────────────────────────────
# Auth / Pairing
# ──────────────────────────────────────────────

async def get_qr_code(session: str) -> bytes:
    """Get QR code image for pairing. Returns raw PNG bytes."""
    url = f"{WAHA_BASE_URL}/api/{session}/auth/qr"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params={"format": "image"}, headers=_headers)
        return response.content


async def request_code(session: str, phone_number: str) -> dict:
    """Request authentication code for pairing by phone number."""
    url = f"{WAHA_BASE_URL}/api/{session}/auth/request-code"
    body = {"phoneNumber": phone_number, "method": None}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=_headers)
        return response.json()


# ──────────────────────────────────────────────
# Calls
# ──────────────────────────────────────────────

async def reject_call(session: str, from_number: str, call_id: str) -> dict:
    """Reject an incoming call."""
    url = f"{WAHA_BASE_URL}/api/{session}/calls/reject"
    body = {"from": from_number, "id": call_id}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=_headers)
        return {"status_code": response.status_code, "body": response.text}


# ──────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────

async def send_text(session: str, to: str, text: str) -> dict:
    """Send a text message."""
    url = f"{WAHA_BASE_URL}/api/sendText"
    body = {"session": session, "chatId": to, "text": text}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=_headers)
        return response.json()


async def send_image(session: str, to: str, image_url: str, caption: str = "") -> dict:
    """Send an image message."""
    url = f"{WAHA_BASE_URL}/api/sendImage"
    body = {"session": session, "chatId": to, "file": {"url": image_url}, "caption": caption}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=_headers)
        return response.json()


# ──────────────────────────────────────────────
# Contacts
# ──────────────────────────────────────────────

async def get_contacts(session: str) -> list:
    """Get all contacts for a session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{WAHA_BASE_URL}/api/contacts",
            params={"session": session},
            headers=_headers
        )
        return response.json()


async def check_number_exists(session: str, phone: str) -> dict:
    """Check if a phone number exists on WhatsApp."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{WAHA_BASE_URL}/api/contacts/check-exists",
            params={"session": session, "phone": phone},
            headers=_headers
        )
        return response.json()

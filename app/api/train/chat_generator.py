import json
import re
import random
import requests
from abc import ABC, abstractmethod
from openai import OpenAI
from google import genai
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────

DEFAULT_MESSAGES_PER_DAY = 50
DEFAULT_HOURS_GAP = 2
DEFAULT_MAX_HOURS = 18
DEFAULT_TOPICS_FILE = str(Path(__file__).parent / "topics.json")
DEFAULT_RETRIES = 3


# ─── Provider Adapters ────────────────────────────────────────────────

class LLMProvider(ABC):
    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        pass


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, endpoint: str | None = None):
        self.model = model
        self.client = OpenAI(base_url=endpoint, api_key=api_key)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content


class OllamaProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint.rstrip("/")
        self.model = model

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        response = requests.post(
            f"{self.endpoint}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "think": False,
                "stream": False,
                "options": {"temperature": 0.4},
            },
            timeout=180,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
        )
        return response.text


# ─── Provider Factory ─────────────────────────────────────────────────

def create_provider(
    provider_type: str,
    model: str,
    api_key: str | None = None,
    endpoint: str | None = None,
) -> LLMProvider:
    """
    Create an LLM provider.

    Args:
        provider_type: "azure", "openai", "ollama", or "gemini"
        model: Model/deployment name
        api_key: API key (required for azure, openai, gemini)
        endpoint: API endpoint URL (required for azure, ollama)
    """
    if provider_type == "azure":
        return OpenAIProvider(endpoint=endpoint, api_key=api_key, model=model)
    elif provider_type == "openai":
        return OpenAIProvider(endpoint=None, api_key=api_key, model=model)
    elif provider_type == "ollama":
        endpoint = endpoint or "http://localhost:11434"
        return OllamaProvider(endpoint=endpoint, model=model)
    elif provider_type == "gemini":
        return GeminiProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown provider: {provider_type}")


# ─── Validation ───────────────────────────────────────────────────────

def validate_provider(provider: LLMProvider):
    """Quick health-check — raises on failure."""
    provider.chat("You are a test.", "Say hi.")


# ─── Time Helpers ─────────────────────────────────────────────────────

def minutes_to_offset(total_minutes: int) -> str:
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def offset_to_minutes(offset: str) -> int:
    parts = offset.split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ─── Prompt Builder ───────────────────────────────────────────────────

def load_topics(topics_file: str = DEFAULT_TOPICS_FILE) -> list:
    path = Path(topics_file)
    if not path.exists():
        return [
            "كرة القدم", "الطعام والطبخ", "السفر", "العمل", "الأفلام والمسلسلات",
            "التكنولوجيا", "الدراسة", "الألعاب الإلكترونية", "الأخبار", "الطقس",
        ]
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_session_prompt(topic: str, start_offset: str = "00:00"):
    return f"""
You write realistic WhatsApp-style chat conversations in Modern Standard Arabic between two friends.

Task:
Write a natural conversation about: {topic}
Make it feel real and spontaneous. Branch into related sub-topics naturally.

Output rules:
- Return ONLY a valid JSON array.
- Do not add any text before or after the JSON.
- Do not use markdown.
- Use double quotes for all JSON keys and values.

Each message must contain:
- "user": 1 or 2
- "text": the message text in Arabic
- "time": time offset in "HH:MM"

Time rules:
- Time is an offset from the start of the conversation (00:00).
- The first message of this session should start at "{start_offset}".
- Increment naturally from there (1-5 min gaps, sometimes instant replies).
- Do NOT jump more than 10 minutes between messages.

Conversation style:
- Natural Modern Standard Arabic.
- Some messages can be very short (one word, emoji).
- The same user CAN send 2-3 messages in a row.
- NEVER repeat the same message or phrase.
- The conversation should branch naturally into sub-topics.
- Vary message lengths.
- Write however many messages feel natural for this conversation — don't force it. A typical chat session is 8-20 messages.
"""


# ─── JSON Parser ──────────────────────────────────────────────────────

def parse_messages(content: str) -> list:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise json.JSONDecodeError("No JSON array found", content, 0)


# ─── Generator ────────────────────────────────────────────────────────

def generate_day(
    provider: LLMProvider,
    target: int = DEFAULT_MESSAGES_PER_DAY,
    hours_gap: int = DEFAULT_HOURS_GAP,
    max_hours: int = DEFAULT_MAX_HOURS,
    topics_file: str = DEFAULT_TOPICS_FILE,
    retries: int = DEFAULT_RETRIES,
) -> list:
    """
    Generate a day's worth of chat messages.

    Args:
        provider: LLM provider instance
        target: minimum number of messages to generate
        hours_gap: hours between chat sessions
        max_hours: hard cap on how far offsets can go (prevents bleeding into next day)
        topics_file: path to JSON file with topic list
        retries: max retries per session on parse failure

    Returns:
        List of message dicts with "user", "text", "time" keys
    """
    topics = load_topics(topics_file)
    all_messages = []
    next_session_start = 0
    used_topics = []
    max_minutes = max_hours * 60

    while len(all_messages) < target:
        if next_session_start >= max_minutes:
            break

        start_offset = minutes_to_offset(next_session_start)

        # Pick a random unused topic
        available = [t for t in topics if t not in used_topics]
        if not available:
            used_topics = []
            available = topics
        topic = random.choice(available)
        used_topics.append(topic)

        # Generate session with retries
        prompt = build_session_prompt(topic=topic, start_offset=start_offset)
        session_messages = None
        for attempt in range(retries):
            raw = provider.chat(prompt, "Generate a conversation.")
            try:
                session_messages = parse_messages(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(session_messages, list):
                break
            session_messages = None

        if not session_messages:
            next_session_start += hours_gap * 60
            continue

        # Drop any messages whose offset exceeds the cap
        session_messages = [
            m for m in session_messages
            if offset_to_minutes(m.get("time", "00:00")) < max_minutes
        ]
        if not session_messages:
            break

        all_messages.extend(session_messages)

        # Next session: last message time + gap
        last_msg_time = offset_to_minutes(all_messages[-1]["time"])
        gap_minutes = hours_gap * 60
        next_session_start = max(last_msg_time + gap_minutes, next_session_start + gap_minutes)

    return all_messages

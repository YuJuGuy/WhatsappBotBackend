"""
Train message generator.

For now: runs in a background thread.
Later: replace _generate with an HTTP call to Azure Function.
"""

import os
import time
import logging
import threading
import psycopg2
from psycopg2.extras import RealDictCursor

from app.api.train.chat_generator import create_provider, generate_day

log = logging.getLogger(__name__)

PG_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:22101975@localhost:5432/postgres")
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_GENERATIONS", "2"))
MAX_RETRIES = 3
_gen_semaphore = threading.Semaphore(MAX_CONCURRENT)


def process_train_session(train_session_id: int, provider_config: dict):
    """
    Kick off generation in the background. Returns immediately.

    Later: swap the thread with requests.post(AZURE_FUNCTION_URL, json={...})
    """
    threading.Thread(
        target=_generate,
        args=(train_session_id, provider_config),
        daemon=True,
    ).start()


def _generate(train_session_id: int, provider_config: dict):
    """Actual generation logic — runs in background thread."""
    with _gen_semaphore, psycopg2.connect(PG_DSN) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM train_session WHERE id = %s AND status = 'generating'",
                (train_session_id,),
            )
            ts = cur.fetchone()
            if not ts:
                log.warning(f"Train session {train_session_id} not found or not in 'generating' status")
                return

        try:
            provider = create_provider(
                provider_type=provider_config["provider_type"],
                model=provider_config["model"],
                api_key=provider_config.get("api_key"),
                endpoint=provider_config.get("endpoint"),
            )
        except Exception as e:
            log.error(f"Failed to create LLM provider for session {train_session_id}: {e}")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE train_session SET status='failed', error_message=%s WHERE id=%s",
                    (str(e), train_session_id),
                )
            conn.commit()
            return

        sid_1 = ts["session_id_1"]
        sid_2 = ts["session_id_2"]
        phone_1 = ts["phone_number_1"]
        phone_2 = ts["phone_number_2"]
        total_days = ts["total_days"]
        msgs_per_day = ts["messages_per_day"]

        try:
            for day_idx in range(total_days):
                day_num = day_idx + 1
                log.info(f"Generating day {day_num}/{total_days} for train session {train_session_id}")

                last_err = None
                day_messages = None
                for attempt in range(MAX_RETRIES):
                    try:
                        day_messages = generate_day(provider, target=msgs_per_day)
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < MAX_RETRIES - 1:
                            wait = 5 * (attempt + 1)
                            log.warning(
                                f"Day {day_num} attempt {attempt+1} failed for session "
                                f"{train_session_id}, retrying in {wait}s: {e}"
                            )
                            time.sleep(wait)
                        else:
                            raise last_err

                with conn.cursor() as cur:
                    for pos, msg in enumerate(day_messages):
                        user = msg.get("user", 1)
                        text = msg.get("text", "")
                        time_offset = msg.get("time", "00:00")

                        if user == 1:
                            sender_sid = sid_1
                            receiver_num = phone_2
                        else:
                            sender_sid = sid_2
                            receiver_num = phone_1

                        cur.execute("""
                            INSERT INTO train_message
                                (train_session_id, sender_session_id, receiver_phone_number,
                                 text, day_number, position, scheduled_at_offset, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                        """, (train_session_id, sender_sid, receiver_num, text, day_num, pos, time_offset))

                conn.commit()
                log.info(f"Day {day_num}: saved {len(day_messages)} messages")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE train_session SET status='generated', error_message=NULL WHERE id=%s",
                    (train_session_id,),
                )
            conn.commit()
            log.info(f"Train session {train_session_id} generation complete")

        except Exception as e:
            log.exception(f"Generation failed for train session {train_session_id}: {e}")
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE train_session SET status='failed', error_message=%s WHERE id=%s",
                    (str(e), train_session_id),
                )
            conn.commit()

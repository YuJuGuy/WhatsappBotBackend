import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from psycopg2.extras import Json, execute_values
from app.db.engine import engine

def insert_outbox(session_id: str, payload: dict, scheduled_at: datetime, user_id: int, priority: int) -> int:
    """
    Insert a single message into outbox_messages table.
    """
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbox_messages (session_id, payload, scheduled_at, status, user_id, priority)
                VALUES (%s, %s, %s, 'pending', %s, %s)
                RETURNING id;
                """,
                (session_id, Json(payload), scheduled_at, user_id, priority),
            )
            outbox_id = cur.fetchone()[0]
            conn.commit()
            return outbox_id
    finally:
        conn.close()

def bulk_insert_outbox(messages: List[Dict[str, Any]], batch_size: int = 1000) -> List[int]:
    """
    Bulk insert messages into outbox_messages table with batching.
    messages: List of dicts with keys: session_id, payload, scheduled_at, user_id
    """
    if not messages:
        return []

    # Prepare rows: (session_id, payload, scheduled_at, 'pending', user_id, priority)
    rows = []
    for msg in messages:
        rows.append((
            msg['session_id'],
            Json(msg['payload']),
            msg['scheduled_at'],
            'pending',
            msg['user_id'],
            msg['priority']
        ))

    all_ids = []
    
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            # Process in batches
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                ids = execute_values(
                    cur,
                    """
                    INSERT INTO outbox_messages (session_id, payload, scheduled_at, status, user_id, priority)
                    VALUES %s
                    RETURNING id;
                    """,
                    batch,
                    fetch=True
                )
                all_ids.extend([x[0] for x in ids])
            
            conn.commit()
    finally:
        conn.close()
            
    return all_ids

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
PG_DSN = os.environ.get("PG_DSN")

try:
    with psycopg2.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            # 1. Drop cancelled_at from outbox_messages
            cur.execute("ALTER TABLE outbox_messages DROP COLUMN IF EXISTS cancelled_at;")
            # 2. Add updated_at to campaignrecipient
            cur.execute("ALTER TABLE campaignrecipient ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;")
            conn.commit()
            print("Migration successful.")
except Exception as e:
    print(f"Error: {e}")

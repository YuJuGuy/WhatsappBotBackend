"""
Lightweight migration script -- run once to add new tables/columns.
Usage:  python db_migrate.py
"""
import os, psycopg2

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:22101975@localhost:5432/postgres"
)

MIGRATIONS = [
    "ALTER TABLE train_session ADD COLUMN IF NOT EXISTS error_message VARCHAR;",

    """CREATE TABLE IF NOT EXISTS autoreplyphonelink (
        rule_id INTEGER NOT NULL REFERENCES messageautoreplyrule(id) ON DELETE CASCADE,
        phone_id INTEGER NOT NULL REFERENCES phone(id) ON DELETE CASCADE,
        PRIMARY KEY (rule_id, phone_id)
    );""",

    """CREATE TABLE IF NOT EXISTS callconfigphonelink (
        config_id INTEGER NOT NULL REFERENCES callautoreplyconfig(id) ON DELETE CASCADE,
        phone_id INTEGER NOT NULL REFERENCES phone(id) ON DELETE CASCADE,
        PRIMARY KEY (config_id, phone_id)
    );""",

    "ALTER TABLE callautoreplyconfig DROP CONSTRAINT IF EXISTS callautoreplyconfig_user_id_key;",

    # Each phone can only belong to one call reject rule
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'callconfigphonelink_phone_id_unique'
        ) THEN
            ALTER TABLE callconfigphonelink ADD CONSTRAINT callconfigphonelink_phone_id_unique UNIQUE (phone_id);
        END IF;
    END $$;""",
]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    for sql in MIGRATIONS:
        print(f"Running: {sql[:80]}...")
        cur.execute(sql)
    cur.close()
    conn.close()
    print("Migrations complete.")


if __name__ == "__main__":
    main()

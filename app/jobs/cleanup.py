from datetime import datetime, timezone
from sqlmodel import select
from app.db.engine import get_session
from app.models.refresh_token import RefreshToken
from app.models.storage import StoredFile
import os


def run_cleanup():
    now = datetime.now(timezone.utc)

    with next(get_session()) as session:

        expired_tokens = session.exec(
            select(RefreshToken).where(RefreshToken.expires_at < now)
        ).all()

        for token in expired_tokens:
            session.delete(token)

        expired_files = session.exec(
            select(StoredFile).where(StoredFile.expires_at != None).where(StoredFile.expires_at < now)
        ).all()

        for file in expired_files:
            try:
                if file.path and os.path.exists(file.path):
                    os.remove(file.path)
            except Exception:
                pass

            session.delete(file)

        session.commit()


if __name__ == "__main__":
    run_cleanup()

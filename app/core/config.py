import os

class Settings:
    PROJECT_NAME: str = "FastAPI NextJS Auth"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-this-prod")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

settings = Settings()

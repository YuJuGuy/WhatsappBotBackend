from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
STORAGE_ROOT = BACKEND_ROOT / "storage"
USER_FILES_ROOT = STORAGE_ROOT / "user-files"


def ensure_storage_dirs() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    USER_FILES_ROOT.mkdir(parents=True, exist_ok=True)


def resolve_storage_path(relative_path: str) -> Path:
    return STORAGE_ROOT / relative_path

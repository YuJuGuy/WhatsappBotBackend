from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_session, require_feature
from app.api.rate_limit import rate_limit_by_user
from app.core.features import Feature
from app.core.storage import USER_FILES_ROOT, ensure_storage_dirs
from app.models.storage import StoredFile
from app.models.user import User
from app.schemas.storage import StoredFileRead


router = APIRouter(dependencies=[Depends(require_feature(Feature.storage))])

ALLOWED_SUFFIXES = {".xlsx", ".xls"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def _user_storage_dir(user_id: int) -> Path:
    ensure_storage_dirs()
    user_dir = USER_FILES_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _get_owned_file(file_id: int, session: Session, current_user: User) -> StoredFile:
    stored_file = session.get(StoredFile, file_id)
    if not stored_file:
        raise HTTPException(status_code=404, detail="Stored file not found")
    if stored_file.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this file")
    return stored_file


def _resolve_file_path(stored_file: StoredFile) -> Path:
    return USER_FILES_ROOT.parent / stored_file.relative_path


@router.post(
    "/",
    response_model=StoredFileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_by_user(20, 60, "storage-upload"))],
)
async def upload_stored_file(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    original_name = Path(file.filename or "").name.strip()
    if not original_name:
        raise HTTPException(status_code=400, detail="A file name is required")

    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files are allowed")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="The uploaded file exceeds the 10 MB limit")

    user_dir = _user_storage_dir(current_user.id)
    stored_name = f"{uuid4().hex}{suffix}"
    stored_path = user_dir / stored_name
    stored_path.write_bytes(contents)

    relative_path = stored_path.relative_to(USER_FILES_ROOT.parent).as_posix()

    stored_file = StoredFile(
        original_name=original_name,
        stored_name=stored_name,
        relative_path=relative_path,
        content_type=file.content_type,
        size_bytes=len(contents),
        user_id=current_user.id,
    )
    session.add(stored_file)
    session.commit()
    session.refresh(stored_file)
    return stored_file


@router.get("/", response_model=list[StoredFileRead])
def list_stored_files(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    files = session.exec(
        select(StoredFile)
        .where(StoredFile.user_id == current_user.id)
        .order_by(StoredFile.created_at.desc())
    ).all()
    return files


@router.get("/{file_id}", response_model=StoredFileRead)
def get_stored_file(
    file_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _get_owned_file(file_id, session, current_user)


@router.get("/{file_id}/download")
def download_stored_file(
    file_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    stored_file = _get_owned_file(file_id, session, current_user)
    file_path = _resolve_file_path(stored_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file content not found")

    media_type = stored_file.content_type or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=stored_file.original_name)


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_by_user(20, 60, "storage-delete"))],
)
def delete_stored_file(
    file_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    stored_file = _get_owned_file(file_id, session, current_user)
    file_path = _resolve_file_path(stored_file)

    if file_path.exists():
        file_path.unlink()

    session.delete(stored_file)
    session.commit()
    return None

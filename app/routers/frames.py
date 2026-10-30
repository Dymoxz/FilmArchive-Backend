import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models import Frame

router = APIRouter(prefix="/api/frames", tags=["Frames"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/{frame_id}/thumbnail")
def get_frame_thumbnail(
    frame_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    frame = db.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame with id {frame_id} not found",
        )

    thumb_path = (
        Path(frame.thumb_image_path)
        if frame.thumb_image_path
        else settings.thumbs_dir / f"{frame.id}.webp"
    )
    if not thumb_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail for frame {frame_id} not found on disk",
        )

    return FileResponse(
        path=thumb_path,
        media_type="image/webp",
        headers=CACHE_HEADERS,
    )


@router.get("/{frame_id}/full")
def get_frame_full(
    frame_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    stmt = (
        select(Frame)
        .options(joinedload(Frame.roll))
        .where(Frame.id == frame_id)
    )
    frame = db.scalar(stmt)
    if frame is None or frame.roll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame with id {frame_id} not found",
        )

    source_path = (settings.scans_dir / frame.roll.folder_name / frame.file_name).resolve()
    scans_root = settings.scans_dir.resolve()
    if not source_path.is_relative_to(scans_root) or not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Full resolution scan for frame {frame_id} not found on disk",
        )

    media_type, _ = mimetypes.guess_type(source_path.name)
    return FileResponse(
        path=source_path,
        media_type=media_type or "image/jpeg",
        filename=frame.file_name,
        headers=CACHE_HEADERS,
    )

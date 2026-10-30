from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models import FilmFormat, Roll
from app.schemas import FrameResponse, RollDetailResponse, RollSummaryResponse

router = APIRouter(prefix="/api/rolls", tags=["Rolls"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("", response_model=list[RollSummaryResponse])
def list_rolls(
    format: Optional[FilmFormat] = Query(
        default=None,
        description="Filter by film format (35MM, HALF_FRAME, MEDIUM_FORMAT)",
    ),
    sort_by: Literal["shoot_date", "date_added"] = Query(
        default="shoot_date",
        description="Sort field: shoot_date (start_date) or date_added",
    ),
    order: Literal["asc", "desc"] = Query(
        default="desc",
        description="Sort direction: asc or desc",
    ),
    tag: Optional[str] = Query(
        default=None,
        description="Filter rolls containing a specific location tag",
    ),
    db: Session = Depends(get_db),
) -> list[RollSummaryResponse]:
    stmt = select(Roll).options(selectinload(Roll.frames))

    if format is not None:
        stmt = stmt.where(Roll.film_format == format)

    sort_column = Roll.start_date if sort_by == "shoot_date" else Roll.date_added
    if order == "asc":
        stmt = stmt.order_by(asc(sort_column), asc(Roll.id))
    else:
        stmt = stmt.order_by(desc(sort_column), desc(Roll.id))

    rolls = db.scalars(stmt).all()

    if tag is not None and tag.strip():
        normalized_tag = tag.strip().lower()
        rolls = [
            r
            for r in rolls
            if any(t.lower() == normalized_tag for t in (r.location_tags or []))
        ]

    return [
        RollSummaryResponse(
            id=roll.id,
            title=roll.title,
            camera=roll.camera,
            film_stock=roll.film_stock,
            film_format=roll.film_format,
            display_date=roll.display_date,
            start_date=roll.start_date,
            end_date=roll.end_date,
            date_added=roll.date_added,
            expected_frames=roll.expected_frames,
            actual_frames_count=len(roll.frames),
            location_tags=roll.location_tags or [],
            cover_url=f"/api/rolls/{roll.id}/cover",
        )
        for roll in rolls
    ]


@router.get("/{roll_id}", response_model=RollDetailResponse)
def get_roll_detail(
    roll_id: int,
    db: Session = Depends(get_db),
) -> RollDetailResponse:
    stmt = (
        select(Roll)
        .options(selectinload(Roll.frames))
        .where(Roll.id == roll_id)
    )
    roll = db.scalar(stmt)
    if roll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Roll with id {roll_id} not found",
        )

    sorted_frames = sorted(roll.frames, key=lambda f: f.frame_number)

    return RollDetailResponse(
        id=roll.id,
        title=roll.title,
        description=roll.description,
        camera=roll.camera,
        lens=roll.lens,
        film_stock=roll.film_stock,
        film_format=roll.film_format,
        display_date=roll.display_date,
        start_date=roll.start_date,
        end_date=roll.end_date,
        date_added=roll.date_added,
        expected_frames=roll.expected_frames,
        location_tags=roll.location_tags or [],
        cover_url=f"/api/rolls/{roll.id}/cover",
        frames=[
            FrameResponse(
                id=frame.id,
                frame_number=frame.frame_number,
                thumbnail_url=f"/api/frames/{frame.id}/thumbnail",
                full_url=f"/api/frames/{frame.id}/full",
            )
            for frame in sorted_frames
        ],
    )


@router.get("/{roll_id}/cover")
def get_roll_cover(
    roll_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    roll = db.get(Roll, roll_id)
    if roll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Roll with id {roll_id} not found",
        )

    cover_path = (
        Path(roll.cover_image_path)
        if roll.cover_image_path
        else settings.covers_dir / f"{roll.id}.webp"
    )
    if not cover_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cover image for roll {roll_id} not found on disk",
        )

    return FileResponse(
        path=cover_path,
        media_type="image/webp",
        headers=CACHE_HEADERS,
    )

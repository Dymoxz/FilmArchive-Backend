from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SyncSummaryResponse
from app.services.sync import run_sync

router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.post("", response_model=SyncSummaryResponse)
def sync_archive(
    force_regenerate: bool = Query(
        default=False,
        description="Force regeneration of all thumbnails and roll cover collages",
    ),
    db: Session = Depends(get_db),
) -> SyncSummaryResponse:
    return run_sync(db=db, force_regenerate=force_regenerate)

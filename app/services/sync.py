import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Frame, Roll
from app.schemas import RollMetadataInput, SyncSummaryResponse
from app.services.imaging import generate_cover_collage, generate_thumbnail

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
FRAME_NUMBER_REGEX = re.compile(r"(\d+)")

_sync_lock = threading.Lock()


def extract_frame_number(filename: str) -> Optional[int]:
    """
    Extract the integer frame number from a scan filename.
    Examples:
      - '01.jpg' -> 1
      - 'frame_12.JPG' -> 12
      - '003_scan.jpg' -> 3
    Extracts the last digit group in the filename stem.
    """
    stem = Path(filename).stem
    matches = FRAME_NUMBER_REGEX.findall(stem)
    if not matches:
        return None
    return int(matches[-1])


def _safe_unlink(file_path: Optional[str | Path]) -> None:
    if not file_path:
        return
    try:
        path = Path(file_path)
        if path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete cached file %s: %s", file_path, exc)


def run_sync(db: Session, force_regenerate: bool = False) -> SyncSummaryResponse:
    if not _sync_lock.acquire(blocking=False):
        return SyncSummaryResponse(
            status="busy",
            rolls_processed=0,
            frames_processed=0,
            errors=["A synchronization job is already in progress."],
        )

    try:
        settings.ensure_directories()
        errors: list[str] = []
        rolls_processed = 0
        frames_processed = 0

        scans_dir = settings.scans_dir
        if not scans_dir.exists() or not scans_dir.is_dir():
            msg = f"Scans directory does not exist or is not accessible: {scans_dir}"
            logger.error(msg)
            return SyncSummaryResponse(
                status="error",
                rolls_processed=0,
                frames_processed=0,
                errors=[msg],
            )

        discovered_folders: set[str] = set()
        subdirs = sorted(
            [p for p in scans_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name,
        )

        for folder_path in subdirs:
            folder_name = folder_path.name
            metadata_path = folder_path / "metadata.json"

            if not metadata_path.is_file():
                warn_msg = f"Skipping '{folder_name}': missing metadata.json"
                logger.warning(warn_msg)
                errors.append(warn_msg)
                continue

            try:
                raw_json = metadata_path.read_text(encoding="utf-8")
                payload = json.loads(raw_json)
                meta = RollMetadataInput.model_validate(payload)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                err_msg = f"Skipping '{folder_name}': invalid metadata.json ({exc})"
                logger.warning(err_msg)
                errors.append(err_msg)
                continue

            discovered_folders.add(folder_name)

            try:
                roll = db.scalar(select(Roll).where(Roll.folder_name == folder_name))
                if roll is None:
                    roll = Roll(
                        folder_name=folder_name,
                        title=meta.title,
                        description=meta.description,
                        camera=meta.camera,
                        lens=meta.lens,
                        film_stock=meta.film_stock,
                        film_format=meta.film_format,
                        expected_frames=meta.expected_frames,
                        start_date=meta.start_date,
                        end_date=meta.end_date,
                        display_date=meta.display_date,
                        location_tags=meta.location_tags,
                    )
                    db.add(roll)
                    db.flush()
                else:
                    roll.title = meta.title
                    roll.description = meta.description
                    roll.camera = meta.camera
                    roll.lens = meta.lens
                    roll.film_stock = meta.film_stock
                    roll.film_format = meta.film_format
                    roll.expected_frames = meta.expected_frames
                    roll.start_date = meta.start_date
                    roll.end_date = meta.end_date
                    roll.display_date = meta.display_date
                    roll.location_tags = meta.location_tags
                    db.flush()

                image_files = sorted(
                    [
                        f
                        for f in folder_path.iterdir()
                        if f.is_file()
                        and not f.name.startswith(".")
                        and f.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                    ],
                    key=lambda f: f.name,
                )

                existing_frames_by_number: dict[int, Frame] = {
                    frame.frame_number: frame for frame in roll.frames
                }
                seen_frame_numbers: set[int] = set()
                frames_changed = False

                for img_path in image_files:
                    frame_num = extract_frame_number(img_path.name)
                    if frame_num is None:
                        warn_msg = (
                            f"Skipping file '{folder_name}/{img_path.name}': "
                            "could not extract frame number from filename"
                        )
                        logger.warning(warn_msg)
                        errors.append(warn_msg)
                        continue

                    if frame_num in seen_frame_numbers:
                        warn_msg = (
                            f"Skipping duplicate frame number {frame_num} in "
                            f"'{folder_name}/{img_path.name}'"
                        )
                        logger.warning(warn_msg)
                        errors.append(warn_msg)
                        continue

                    seen_frame_numbers.add(frame_num)

                    frame = existing_frames_by_number.get(frame_num)
                    file_changed = False
                    if frame is None:
                        frame = Frame(
                            roll_id=roll.id,
                            frame_number=frame_num,
                            file_name=img_path.name,
                        )
                        db.add(frame)
                        db.flush()
                        frames_changed = True
                    else:
                        if frame.file_name != img_path.name:
                            frame.file_name = img_path.name
                            file_changed = True
                            frames_changed = True
                            db.flush()

                    thumb_dest = settings.thumbs_dir / f"{frame.id}.webp"
                    needs_thumb = (
                        force_regenerate
                        or file_changed
                        or not frame.thumb_image_path
                        or not Path(frame.thumb_image_path).is_file()
                    )

                    if needs_thumb:
                        try:
                            generate_thumbnail(img_path, thumb_dest)
                            frame.thumb_image_path = str(thumb_dest)
                        except Exception as exc:
                            err_msg = (
                                f"Failed to generate thumbnail for "
                                f"'{folder_name}/{img_path.name}': {exc}"
                            )
                            logger.error(err_msg)
                            errors.append(err_msg)

                    frames_processed += 1

                # Delete any Frame records for this roll whose source files no longer exist
                for existing_num, existing_frame in list(existing_frames_by_number.items()):
                    if existing_num not in seen_frame_numbers:
                        _safe_unlink(existing_frame.thumb_image_path)
                        _safe_unlink(settings.thumbs_dir / f"{existing_frame.id}.webp")
                        db.delete(existing_frame)
                        frames_changed = True

                db.flush()
                db.refresh(roll)

                # Cover Collage Generation
                cover_dest = settings.covers_dir / f"{roll.id}.webp"
                needs_cover = (
                    force_regenerate
                    or frames_changed
                    or not roll.cover_image_path
                    or not Path(roll.cover_image_path).is_file()
                )

                if needs_cover:
                    sorted_frames = sorted(roll.frames, key=lambda fr: fr.frame_number)[:4]
                    if len(sorted_frames) >= 4:
                        # Prefer cached thumbnails for the 4-frame 390x390 collage, fallback to full scan
                        collage_sources = [
                            Path(fr.thumb_image_path)
                            if fr.thumb_image_path and Path(fr.thumb_image_path).is_file()
                            else (folder_path / fr.file_name)
                            for fr in sorted_frames
                        ]
                    else:
                        # For 1-3 frames, 800x800 full-bleed cover benefits from source scan resolution
                        collage_sources = [
                            (folder_path / fr.file_name)
                            if (folder_path / fr.file_name).is_file()
                            else Path(fr.thumb_image_path)
                            for fr in sorted_frames
                            if (folder_path / fr.file_name).is_file()
                            or (fr.thumb_image_path and Path(fr.thumb_image_path).is_file())
                        ]

                    try:
                        generate_cover_collage(collage_sources, cover_dest)
                        roll.cover_image_path = str(cover_dest)
                    except Exception as exc:
                        err_msg = f"Failed to generate cover collage for '{folder_name}': {exc}"
                        logger.error(err_msg)
                        errors.append(err_msg)

                db.commit()
                rolls_processed += 1

            except Exception as exc:
                db.rollback()
                err_msg = f"Error syncing roll '{folder_name}': {exc}"
                logger.exception(err_msg)
                errors.append(err_msg)

        # Prune deleted rolls whose folders no longer exist on disk
        all_db_rolls = db.scalars(select(Roll)).all()
        for db_roll in all_db_rolls:
            folder_on_disk = scans_dir / db_roll.folder_name
            if db_roll.folder_name not in discovered_folders and not folder_on_disk.exists():
                try:
                    for frame in db_roll.frames:
                        _safe_unlink(frame.thumb_image_path)
                        _safe_unlink(settings.thumbs_dir / f"{frame.id}.webp")
                    _safe_unlink(db_roll.cover_image_path)
                    _safe_unlink(settings.covers_dir / f"{db_roll.id}.webp")
                    db.delete(db_roll)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    err_msg = f"Failed to prune deleted roll '{db_roll.folder_name}': {exc}"
                    logger.error(err_msg)
                    errors.append(err_msg)

        return SyncSummaryResponse(
            status="ok",
            rolls_processed=rolls_processed,
            frames_processed=frames_processed,
            errors=errors,
        )
    finally:
        _sync_lock.release()

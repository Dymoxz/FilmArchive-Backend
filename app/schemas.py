from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import FilmFormat


class RollMetadataInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_stock: Optional[str] = None
    film_format: FilmFormat
    expected_frames: int = Field(..., gt=0)
    start_date: date
    end_date: Optional[date] = None
    display_date: str = Field(..., min_length=1)
    location_tags: list[str] = Field(default_factory=list)

    @field_validator("description", "camera", "lens", "film_stock", "end_date", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("film_format", mode="before")
    @classmethod
    def normalize_film_format(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper().replace("-", "_").replace(" ", "_")
        return value

    @field_validator("location_tags", mode="before")
    @classmethod
    def ensure_list_of_strings(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("location_tags must be a list of strings")
        return [str(item).strip() for item in value if str(item).strip()]


class FrameResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    frame_number: int
    thumbnail_url: str
    full_url: str


class RollSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    camera: Optional[str] = None
    film_stock: Optional[str] = None
    film_format: FilmFormat
    display_date: str
    start_date: date
    end_date: Optional[date] = None
    date_added: datetime
    expected_frames: int
    actual_frames_count: int
    location_tags: list[str]
    cover_url: str


class RollDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_stock: Optional[str] = None
    film_format: FilmFormat
    display_date: str
    start_date: date
    end_date: Optional[date] = None
    date_added: datetime
    expected_frames: int
    location_tags: list[str]
    cover_url: str
    frames: list[FrameResponse]


class SyncSummaryResponse(BaseModel):
    status: str = "ok"
    rolls_processed: int
    frames_processed: int
    errors: list[str] = Field(default_factory=list)


class ArchiveStatsResponse(BaseModel):
    total_rolls: int
    total_frames: int

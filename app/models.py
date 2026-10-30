from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FilmFormat(str, enum.Enum):
    THIRTY_FIVE_MM = "35MM"
    HALF_FRAME = "HALF_FRAME"
    MEDIUM_FORMAT = "MEDIUM_FORMAT"


class Roll(Base):
    __tablename__ = "rolls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    camera: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lens: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    film_stock: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    film_format: Mapped[FilmFormat] = mapped_column(
        Enum(FilmFormat, values_callable=lambda obj: [e.value for e in obj]),
        index=True,
        nullable=False,
    )
    expected_frames: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    display_date: Mapped[str] = mapped_column(String, nullable=False)
    location_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    date_added: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    cover_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    frames: Mapped[list[Frame]] = relationship(
        "Frame",
        back_populates="roll",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Frame.frame_number.asc()",
    )


class Frame(Base):
    __tablename__ = "frames"
    __table_args__ = (
        UniqueConstraint("roll_id", "frame_number", name="uq_roll_frame_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roll_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rolls.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    frame_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    thumb_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    roll: Mapped[Roll] = relationship("Roll", back_populates="frames")

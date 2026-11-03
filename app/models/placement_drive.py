
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlacementDrive(Base):
    __tablename__ = "placement_drives"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    company_name: Mapped[str] = mapped_column(
        String(150), nullable=False, index=True
    )

    job_role: Mapped[str] = mapped_column(
        String(150), nullable=False
    )

    package_lpa: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    minimum_cgpa: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    eligible_branches: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )

    graduation_year: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    maximum_active_backlogs: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    maximum_total_backlogs: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    application_deadline: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )

    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )

    created_by: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

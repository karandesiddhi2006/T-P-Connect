
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecruitmentRound(Base):
    __tablename__ = "recruitment_rounds"

    __table_args__ = (
        UniqueConstraint(
            "drive_id",
            "round_number",
            name="uq_drive_round_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    drive_id: Mapped[int] = mapped_column(
        ForeignKey("placement_drives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    round_number: Mapped[int] = mapped_column(Integer, nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

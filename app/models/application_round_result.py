
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


class ApplicationRoundResult(Base):
    __tablename__ = "application_round_results"

    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "round_id",
            name="uq_application_round_result",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    round_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_rounds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )

    score: Mapped[float | None] = mapped_column(nullable=True)

    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

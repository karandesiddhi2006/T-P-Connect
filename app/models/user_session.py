
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    csrf_token: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    expires_at: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    __table_args__ = (
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

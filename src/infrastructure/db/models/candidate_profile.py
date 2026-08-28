from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class CandidateProfileModel(Base):
    """Reflet de la table ``candidate_profile`` (voir ``sql/tables.sql``)."""

    __tablename__ = "candidate_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_name: Mapped[str] = mapped_column(String(200), nullable=False)
    headline: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    cv_raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    skills: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    experiences: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    education: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("profile_name", name="uq_candidate_profile_name"),
        CheckConstraint("jsonb_typeof(cv_raw_json) = 'object'", name="chk_candidate_cv_raw_json"),
        CheckConstraint("jsonb_typeof(skills) = 'array'", name="chk_candidate_skills_array"),
        CheckConstraint("jsonb_typeof(experiences) = 'array'", name="chk_candidate_experiences_array"),
        CheckConstraint("jsonb_typeof(education) = 'array'", name="chk_candidate_education_array"),
        Index(
            "uq_candidate_profile_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateProfileModel(id={self.id}, profile_name='{self.profile_name}', "
            f"headline='{self.headline}')>"
        )

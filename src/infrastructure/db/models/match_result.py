from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class MatchResultModel(Base):
    """Reflet de la table ``match_result`` (voir ``sql/tables.sql``)."""

    __tablename__ = "match_result"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_offer.id", ondelete="CASCADE"), nullable=False
    )
    candidate_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strengths: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    weaknesses: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    missing_skills: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("job_offer_id", "candidate_profile_id", name="uq_match_unique_pair"),
        CheckConstraint("total_score >= 0 AND total_score <= 100", name="chk_match_total_score"),
        CheckConstraint("jsonb_typeof(score_breakdown) = 'object'", name="chk_match_score_breakdown_object"),
        CheckConstraint("jsonb_typeof(strengths) = 'array'", name="chk_match_strengths_array"),
        CheckConstraint("jsonb_typeof(weaknesses) = 'array'", name="chk_match_weaknesses_array"),
        CheckConstraint("jsonb_typeof(missing_skills) = 'array'", name="chk_match_missing_skills_array"),
        Index("idx_match_result_job_offer_id", "job_offer_id"),
        Index("idx_match_result_candidate_profile_id", "candidate_profile_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<MatchResultModel(id={self.id}, job_offer_id={self.job_offer_id}, "
            f"candidate_profile_id={self.candidate_profile_id}, total_score={self.total_score})>"
        )

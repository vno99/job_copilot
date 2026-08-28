from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class LetterVersionModel(Base):
    """Reflet de la table ``letter_version`` (voir ``sql/tables.sql``)."""

    __tablename__ = "letter_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_offer.id", ondelete="CASCADE"), nullable=False
    )
    candidate_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("candidate_profile.id", ondelete="CASCADE"), nullable=False
    )
    match_result_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("match_result.id", ondelete="SET NULL")
    )
    letter_content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    letter_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Une seule lettre par couple (offre, profil) : la génération remplace
        # l'existant.
        UniqueConstraint(
            "job_offer_id", "candidate_profile_id", name="uq_letter_version_pair"
        ),
        CheckConstraint(
            "jsonb_typeof(letter_content_json) = 'object'", name="chk_letter_content_object"
        ),
        Index("idx_letter_version_job_offer_id", "job_offer_id"),
        Index("idx_letter_version_candidate_profile_id", "candidate_profile_id"),
        Index("idx_letter_version_match_result_id", "match_result_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<LetterVersionModel(id={self.id}, job_offer_id={self.job_offer_id}, "
            f"candidate_profile_id={self.candidate_profile_id})>"
        )

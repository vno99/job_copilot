from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class CVVersionModel(Base):
    """Reflet de la table ``cv_version`` (voir ``sql/tables.sql``)."""

    __tablename__ = "cv_version"

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
    cv_content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cv_text: Mapped[Optional[str]] = mapped_column(Text)
    tailoring_notes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Suivi « candidature envoyée » : marqué par l'utilisateur pour un couple
    # (offre, profil) une fois le CV généré. Préservé à la régénération du CV
    # (l'upsert ne met à jour que les clés du record, qui ne l'inclut pas).
    application_submitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Un seul CV par couple (offre, profil) : la génération remplace l'existant.
        UniqueConstraint(
            "job_offer_id", "candidate_profile_id", name="uq_cv_version_pair"
        ),
        CheckConstraint("jsonb_typeof(cv_content_json) = 'object'", name="chk_cv_content_object"),
        CheckConstraint("jsonb_typeof(tailoring_notes) = 'array'", name="chk_cv_tailoring_notes_array"),
        Index("idx_cv_version_job_offer_id", "job_offer_id"),
        Index("idx_cv_version_candidate_profile_id", "candidate_profile_id"),
        Index("idx_cv_version_match_result_id", "match_result_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CVVersionModel(id={self.id}, job_offer_id={self.job_offer_id}, "
            f"candidate_profile_id={self.candidate_profile_id})>"
        )

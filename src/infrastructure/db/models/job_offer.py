from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


class JobOfferModel(Base):
    """Reflet de la table ``job_offer`` (voir ``sql/tables.sql``)."""

    __tablename__ = "job_offer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    company: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    contract_type: Mapped[Optional[str]] = mapped_column(String(100))
    published_date: Mapped[Optional[date]] = mapped_column(Date)
    experience: Mapped[Optional[str]] = mapped_column(Text)
    diploma: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    skills_extracted: Mapped[Optional[dict]] = mapped_column(JSONB)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_job_offer_source_external"),
        CheckConstraint("url <> ''", name="chk_job_offer_url"),
        CheckConstraint("jsonb_typeof(raw_payload) = 'object'", name="chk_job_offer_raw_payload"),
        CheckConstraint("jsonb_typeof(skills_extracted) = 'object'", name="chk_job_offer_skills_object"),
        Index("idx_job_offer_source", "source"),
        Index("idx_job_offer_company", "company"),
        Index("idx_job_offer_published_date", "published_date"),
        Index("idx_job_offer_contract_type", "contract_type"),
        Index("idx_job_offer_content_hash", "content_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<JobOfferModel(id={self.id}, source='{self.source}', "
            f"source_job_id='{self.source_job_id}', title='{self.title}')>"
        )

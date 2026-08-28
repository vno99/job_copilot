from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class SearchParameterModel(Base):
    """Reflet de la table ``search_parameters`` (voir ``sql/tables.sql``)."""

    __tablename__ = "search_parameters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    max_offers: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    # Actif = traité par l'agent de recherche ; ``default=True`` (Python) pour
    # que la valeur soit connue en mémoire dès l'insertion (le Pydantic de
    # création ne fournit pas le champ, contrairement à ``max_offers``).
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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
        UniqueConstraint("url", name="uq_search_parameters_url"),
        CheckConstraint(
            "max_offers >= 1 AND max_offers <= 20",
            name="chk_search_parameters_max_offers",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SearchParameterModel(id={self.id}, title='{self.title}', "
            f"source='{self.source}')>"
        )

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ESGArticle(Base):
    __tablename__ = "esg_articles"

    article_id:          Mapped[str]             = mapped_column(String(32),  primary_key=True)
    title:               Mapped[str]             = mapped_column(Text,        nullable=False)
    url:                 Mapped[str]             = mapped_column(Text,        nullable=False, unique=True)
    published_date:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_name:         Mapped[str | None]      = mapped_column(String(120))
    author:              Mapped[str | None]      = mapped_column(String(200))
    body_text:           Mapped[str | None]      = mapped_column(Text)
    esg_category:        Mapped[str | None]      = mapped_column(String(30))
    category_confidence: Mapped[float | None]    = mapped_column(Float)
    fetched_via:         Mapped[str | None]      = mapped_column(String(20))
    gemini_summary:      Mapped[str | None]      = mapped_column(Text)
    ingested_at:         Mapped[datetime]        = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_published_date", published_date.desc()),
        Index("ix_source_name",    source_name),
        Index("ix_esg_category",   esg_category),
    )

    def __repr__(self) -> str:
        return f"<ESGArticle [{self.esg_category}] '{self.title[:45]}'>"

from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Float, Index, String, Text, Boolean, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ESGArticle(Base):
    __tablename__ = "esg_articles"

    # core fields
    article_id:          Mapped[str]             = mapped_column(String(32),  primary_key=True)
    title:               Mapped[str]             = mapped_column(Text,        nullable=False)
    url:                 Mapped[str]             = mapped_column(Text,        nullable=False)
    published_date:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_name:         Mapped[str | None]      = mapped_column(String(120))
    author:              Mapped[str | None]      = mapped_column(String(200))
    body_text:           Mapped[str | None]      = mapped_column(Text)
    fetched_via:         Mapped[str | None]      = mapped_column(String(20))

    # classification
    esg_category:        Mapped[str | None]      = mapped_column(String(60))
    category_confidence: Mapped[float | None]    = mapped_column(Float)
    relevant:            Mapped[bool | None]     = mapped_column(Boolean)
    priority:            Mapped[str | None]      = mapped_column(String(10))
    action:              Mapped[str | None]      = mapped_column(Text)
    reason:              Mapped[str | None]      = mapped_column(Text)

    # primary ESG fields (comma-separated)
    primary_fields:      Mapped[str | None]      = mapped_column(Text)

    # AI metadata
    sentiment:           Mapped[str | None]      = mapped_column(String(10))   # positive/negative/neutral
    entities:            Mapped[str | None]      = mapped_column(Text)         # JSON: {companies, govt_bodies}
    tags:                Mapped[str | None]      = mapped_column(Text)         # comma-separated key topics
    gemini_summary:      Mapped[str | None]      = mapped_column(Text)

    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_published_date", published_date.desc()),
        Index("ix_esg_category",   esg_category),
        Index("ix_priority",       priority),
        Index("ix_relevant",       relevant),
        Index("ix_sentiment",      sentiment),
    )
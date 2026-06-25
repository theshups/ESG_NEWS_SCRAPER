from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from src.components.base import BaseStorage
from src.components.models import Base, ESGArticle
from src.exception import ConfigError, StorageError
from src.logger import get_logger

load_dotenv()
log = get_logger(__name__)


def _build_url() -> str:
    pw = os.getenv("POSTGRES_PASSWORD", "")
    if not pw:
        raise ConfigError("POSTGRES_PASSWORD is not set in .env")
    return (
        "postgresql+psycopg2://"
        + os.getenv("POSTGRES_USER", "postgres") + ":" + pw
        + "@" + os.getenv("POSTGRES_HOST", "localhost")
        + ":" + os.getenv("POSTGRES_PORT", "5432")
        + "/" + os.getenv("POSTGRES_DB", "esg_intel")
    )


class PostgreSQLStorage(BaseStorage):

    def __init__(self, url: str = None):
        try:
            self._engine = create_engine(
                url or _build_url(),
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                echo=False,
            )
            self.setup()
        except ConfigError:
            raise
        except Exception as e:
            raise StorageError("cannot connect to PostgreSQL: " + str(e))

    def setup(self) -> None:
        Base.metadata.create_all(self._engine)
        migrations = [
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS fetched_via VARCHAR(20)",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS gemini_summary TEXT",
        ]
        with self._engine.begin() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                except Exception:
                    pass
        log.info("postgres schema ready")

    def save(self, articles: list) -> int:
        if not articles:
            return 0
        inserted = 0
        with Session(self._engine) as session:
            for a in articles:
                if session.get(ESGArticle, a.article_id):
                    continue
                existing = session.scalar(
                    select(ESGArticle).where(ESGArticle.url == a.url).limit(1)
                )
                if existing:
                    continue
                session.add(ESGArticle(
                    article_id          = a.article_id,
                    title               = a.title,
                    url                 = a.url,
                    published_date      = a.published_date,
                    source_name         = a.source_name,
                    author              = a.author,
                    body_text           = a.body_text,
                    esg_category        = a.esg_category,
                    category_confidence = a.confidence,
                    fetched_via         = getattr(a, "fetched_via", "requests"),
                ))
                inserted += 1
            session.commit()
        log.info("saved " + str(inserted) + " new  /  " + str(len(articles) - inserted) + " duplicates skipped")
        return inserted

    def recent(self, n: int = 50) -> list:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .order_by(ESGArticle.published_date.desc().nullslast())
                .limit(n)
            ).all()
            return [_to_dict(r) for r in rows]

    def get_by_id(self, article_id: str):
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            return _to_dict(row) if row else None

    def get_by_category(self, category: str, n: int = 50) -> list:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .where(ESGArticle.esg_category == category)
                .order_by(ESGArticle.published_date.desc())
                .limit(n)
            ).all()
            return [_to_dict(r) for r in rows]

    def save_summary(self, article_id: str, summary: str) -> None:
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            if row:
                row.gemini_summary = summary
                session.commit()

    def delete_old_articles(self, days: int = 7) -> int:
        """
        Hard deletes all articles whose published_date is older than `days`.
        Called at the end of every pipeline run to keep the DB fresh.
        Returns the number of rows deleted.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0
        with Session(self._engine) as session:
            old_rows = session.scalars(
                select(ESGArticle).where(ESGArticle.published_date < cutoff)
            ).all()
            deleted = len(old_rows)
            for row in old_rows:
                session.delete(row)
            session.commit()
        if deleted:
            log.info("Deleted " + str(deleted) + " articles older than " + str(days) + " days")
        else:
            log.info("No articles older than " + str(days) + " days found")
        return deleted

    def get_summary(self, article_id: str) -> str:
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            return (row.gemini_summary or "") if row else ""

    def summary(self) -> dict:
        with Session(self._engine) as session:
            total = session.scalar(select(func.count()).select_from(ESGArticle))
            per_source = session.execute(
                select(ESGArticle.source_name, func.count().label("cnt"))
                .group_by(ESGArticle.source_name)
                .order_by(func.count().desc())
            ).all()
            per_cat = session.execute(
                select(
                    func.coalesce(ESGArticle.esg_category, "Unclassified").label("cat"),
                    func.count().label("cnt"),
                )
                .group_by("cat")
                .order_by(func.count().desc())
            ).all()
            per_via = session.execute(
                select(
                    func.coalesce(ESGArticle.fetched_via, "unknown").label("via"),
                    func.count().label("cnt"),
                )
                .group_by("via")
            ).all()
        return {
            "total":       total or 0,
            "by_source":   {r.source_name: r.cnt for r in per_source},
            "by_category": {r.cat: r.cnt for r in per_cat},
            "by_method":   {r.via: r.cnt for r in per_via},
        }


def _to_dict(row) -> dict:
    if row is None:
        return {}
    return {
        "article_id":     row.article_id,
        "title":          row.title,
        "url":            row.url,
        "date":           row.published_date.isoformat() if row.published_date else None,
        "source":         row.source_name,
        "author":         row.author,
        "category":       row.esg_category,
        "confidence":     row.category_confidence,
        "body_text":      row.body_text,
        "gemini_summary": row.gemini_summary,
        "via":            row.fetched_via,
    }
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
                pool_size=5, max_overflow=10,
                pool_pre_ping=True, echo=False,
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
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS relevant BOOLEAN",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS priority VARCHAR(10)",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS action TEXT",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS reason TEXT",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS primary_fields TEXT",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS sentiment VARCHAR(10)",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS entities TEXT",
            "ALTER TABLE esg_articles ADD COLUMN IF NOT EXISTS tags TEXT",
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
                existing = session.scalar(select(ESGArticle).where(ESGArticle.url == a.url).limit(1))
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
                    fetched_via         = getattr(a, "fetched_via", "requests"),
                    esg_category        = getattr(a, "esg_category", None),
                    category_confidence = getattr(a, "confidence", None),
                    relevant            = getattr(a, "relevant", True),
                    priority            = getattr(a, "priority", "low"),
                    action              = getattr(a, "action", None),
                    reason              = getattr(a, "reason", None),
                    primary_fields      = getattr(a, "primary_fields", None),
                    sentiment           = getattr(a, "sentiment", None),
                    entities            = getattr(a, "entities", None),
                    tags                = getattr(a, "tags", None),
                ))
                inserted += 1
            session.commit()
        log.info("saved " + str(inserted) + " new  /  " + str(len(articles) - inserted) + " duplicates skipped")
        return inserted

    def recent(self, n: int = 60, relevant_only: bool = False) -> list:
        with Session(self._engine) as session:
            q = select(ESGArticle).order_by(ESGArticle.published_date.desc().nullslast())
            if relevant_only:
                q = q.where(ESGArticle.relevant == True)
            return [_to_dict(r) for r in session.scalars(q.limit(n)).all()]

    def get_by_category(self, category: str, n: int = 60) -> list:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .where(ESGArticle.esg_category == category)
                .order_by(ESGArticle.published_date.desc())
                .limit(n)
            ).all()
            return [_to_dict(r) for r in rows]

    def get_by_priority(self, priority: str, n: int = 60) -> list:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .where(ESGArticle.priority == priority)
                .where(ESGArticle.relevant == True)
                .order_by(ESGArticle.published_date.desc())
                .limit(n)
            ).all()
            return [_to_dict(r) for r in rows]

    def get_by_id(self, article_id: str):
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            return _to_dict(row) if row else None

    def save_summary(self, article_id: str, summary: str) -> None:
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            if row:
                row.gemini_summary = summary
                session.commit()

    def get_summary(self, article_id: str) -> str:
        with Session(self._engine) as session:
            row = session.get(ESGArticle, article_id)
            return (row.gemini_summary or "") if row else ""

    def delete_irrelevant(self) -> int:
        """Permanently removes Irrelevant articles from the database."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle).where(
                    (ESGArticle.esg_category == "Irrelevant") |
                    (ESGArticle.relevant == False)
                )
            ).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
        if count:
            log.info("Removed " + str(count) + " irrelevant articles")
        return count

    def delete_old_articles(self, days: int = 7) -> int:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with Session(self._engine) as session:
            old = session.scalars(select(ESGArticle).where(ESGArticle.published_date < cutoff)).all()
            count = len(old)
            for row in old:
                session.delete(row)
            session.commit()
        if count:
            log.info("Deleted " + str(count) + " articles older than " + str(days) + " days")
        return count

    def summary(self) -> dict[str, Any]:
        with Session(self._engine) as session:
            total     = session.scalar(select(func.count()).select_from(ESGArticle)) or 0
            relevant  = session.scalar(
                select(func.count()).select_from(ESGArticle).where(ESGArticle.relevant == True)
            ) or 0
            by_cat = {r.cat: r.cnt for r in session.execute(
                select(func.coalesce(ESGArticle.esg_category,"Unclassified").label("cat"), func.count().label("cnt"))
                .where(ESGArticle.relevant == True)
                .group_by("cat").order_by(func.count().desc())
            ).all()}
            by_pri = {r.pri: r.cnt for r in session.execute(
                select(func.coalesce(ESGArticle.priority,"none").label("pri"), func.count().label("cnt"))
                .where(ESGArticle.relevant == True)
                .group_by("pri").order_by(func.count().desc())
            ).all()}
            by_src = {r.source_name: r.cnt for r in session.execute(
                select(ESGArticle.source_name, func.count().label("cnt"))
                .group_by(ESGArticle.source_name).order_by(func.count().desc())
            ).all()}
            by_sent = {r.s: r.cnt for r in session.execute(
                select(func.coalesce(ESGArticle.sentiment,"unknown").label("s"), func.count().label("cnt"))
                .where(ESGArticle.relevant == True)
                .group_by("s").order_by(func.count().desc())
            ).all()}
        return {
            "total": total, "relevant": relevant,
            "by_category": by_cat, "by_priority": {},
            "by_source": by_src, "by_sentiment": by_sent,
        }


def _to_dict(row: ESGArticle) -> dict:
    if not row:
        return {}
    return {
        "article_id":    row.article_id,
        "title":         row.title,
        "url":           row.url,
        "date":          row.published_date.isoformat() if row.published_date else None,
        "source":        row.source_name,
        "author":        row.author,
        "category":      row.esg_category,
        "confidence":    row.category_confidence,
        "body_text":     row.body_text,
        "via":           row.fetched_via,
        "relevant":      row.relevant,
        "priority":      row.priority,
        "action":        row.action,
        "reason":        row.reason,
        "primary_fields":row.primary_fields,
        "sentiment":     row.sentiment,
        "entities":      row.entities,
        "tags":          row.tags,
        "gemini_summary":row.gemini_summary,
    }
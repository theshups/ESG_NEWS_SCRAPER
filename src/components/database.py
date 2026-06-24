from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, text, text
from sqlalchemy.orm import Session

from src.components.base import BaseStorage
from src.components.models import Base, ESGArticle
from src.components.scraper import Article
from src.exception import ConfigError, StorageError
from src.logger import get_logger

load_dotenv()
log = get_logger(__name__)


def _build_url() -> str:
    pw = os.getenv("POSTGRES_PASSWORD", "shups.69")
    if not pw:
        raise ConfigError(
            "POSTGRES_PASSWORD is not set.\n"
            "  1. Copy .env.example → .env\n"
            "  2. Fill in your postgres password\n"
            "  3. Make sure PostgreSQL is running"
        )
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "esg_intel")
    user = os.getenv("POSTGRES_USER", "postgres")
    return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"


class PostgreSQLStorage(BaseStorage):

    def __init__(self, url: str = None):
        try:
            self._engine = create_engine(
                url or _build_url(),
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,   # auto-reconnect stale connections
                echo=False,
            )
            self.setup()
        except ConfigError:
            raise
        except Exception as e:
            raise StorageError(
                f"cannot connect to PostgreSQL: {e}\n"
                "  Make sure postgres is running and your .env credentials are correct."
            )

    def setup(self) -> None:    # override
        Base.metadata.create_all(self._engine)
        log.info("postgres schema ready")

    def save(self, articles: list[Article]) -> int:    # override
        if not articles:
            return 0

        inserted = 0
        with Session(self._engine) as session:
            for a in articles:
                # check by primary key — skip if we already have it
                if session.get(ESGArticle, a.article_id):
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
                    fetched_via         = a.fetched_via,
                ))
                inserted += 1

            session.commit()

        log.info(f"saved {inserted} new  /  {len(articles) - inserted} duplicates skipped")
        return inserted

    def recent(self, n: int = 20) -> list[dict]:    # override
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .order_by(ESGArticle.published_date.desc().nullslast())
                .limit(n)
            ).all()
            return [_row_dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:    # override
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
                select(ESGArticle.fetched_via, func.count().label("cnt"))
                .group_by(ESGArticle.fetched_via)
            ).all()

        return {
            "total":       total or 0,
            "by_source":   {r.source_name: r.cnt for r in per_source},
            "by_category": {r.cat: r.cnt for r in per_cat},
            "by_method":   {r.fetched_via: r.cnt for r in per_via},
        }

    def get_by_category(self, category: str, n: int = 10) -> list[dict]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(ESGArticle)
                .where(ESGArticle.esg_category == category)
                .order_by(ESGArticle.published_date.desc())
                .limit(n)
            ).all()
            return [_row_dict(r) for r in rows]


def _row_dict(row: ESGArticle) -> dict:
    return {
        "article_id": row.article_id,
        "title":      row.title,
        "url":        row.url,
        "date":       row.published_date.isoformat() if row.published_date else None,
        "source":     row.source_name,
        "author":     row.author,
        "category":   row.esg_category,
        "confidence": row.category_confidence,
        "via":        row.fetched_via,
    }

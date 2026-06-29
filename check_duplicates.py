from __future__ import annotations
from dotenv import load_dotenv; load_dotenv()
from src.components.database import PostgreSQLStorage
from src.components.models import ESGArticle
from sqlalchemy import select
from sqlalchemy.orm import Session
from rapidfuzz import fuzz

def check_similar_titles():
    db = PostgreSQLStorage()
    with Session(db._engine) as session:
        rows = session.scalars(
            select(ESGArticle)
            .order_by(ESGArticle.published_date.desc())
            .limit(100)
        ).all()

        print("Checking for similar titles...\n")
        duplicates = []
        for i, a in enumerate(rows):
            for b in rows[i+1:]:
                score = fuzz.token_sort_ratio(
                    (a.title or "").lower(),
                    (b.title or "").lower()
                )
                if score >= 80:
                    duplicates.append((score, a.title, b.title, a.source_name, b.source_name))

        if not duplicates:
            print("No similar articles found.")
            return

        duplicates.sort(reverse=True)
        print(str(len(duplicates)) + " similar pairs found:\n")
        for score, t1, t2, s1, s2 in duplicates[:20]:
            print("  [" + str(score) + "%]  " + s1 + ": " + (t1 or "")[:50])
            print("         " + s2 + ": " + (t2 or "")[:50])
            print()

check_similar_titles()
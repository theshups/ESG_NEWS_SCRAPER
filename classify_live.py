from dotenv import load_dotenv; load_dotenv()
import sys, time
from src.components.database import PostgreSQLStorage
from src.components.ollama_classifier import OllamaClassifier, MAX_WORKERS
from src.components.models import ESGArticle
from sqlalchemy import select
from sqlalchemy.orm import Session

SENT_ICON = {"positive": "+", "negative": "-", "neutral": "~"}

db  = PostgreSQLStorage()
clf = OllamaClassifier()
clf.load()

if not clf.ready:
    print("Ollama not running. Check ollama serve")
    sys.exit(1)

with Session(db._engine) as session:
    rows = session.scalars(
        select(ESGArticle)
        .where(ESGArticle.esg_category == None)
        .order_by(ESGArticle.published_date.desc())
        .limit(300)
    ).all()

    total = len(rows)
    if not total:
        print("No unclassified articles. Run make scrape first.")
        sys.exit(0)

    print()
    print("=" * 75)
    print("  ESG Classifier  |  Model: " + str(clf._model) + "  |  Workers: " + str(MAX_WORKERS) + "  |  Articles: " + str(total))
    print("=" * 75)

    articles = [{"title": r.title or "", "body": r.body_text or ""} for r in rows]

    start   = time.time()
    results = clf.classify_batch(articles)

    # main thread only updates ORM — no commits in workers
    for i, (row, r) in enumerate(zip(rows, results), 1):
        row.esg_category        = r.get("category", "Irrelevant")
        row.relevant            = bool(r.get("relevant", False))
        row.sentiment           = r.get("sentiment", "neutral")
        row.action              = r.get("action", "No action.")
        row.reason              = r.get("reason", "")
        row.primary_fields      = r.get("primary_fields", "")
        row.tags                = r.get("tags", "")
        row.entities            = r.get("entities", "{}")
        row.category_confidence = float(r.get("confidence", 0.0))
        row.priority            = "none"

        rel  = "REL" if row.relevant else "   "
        icon = SENT_ICON.get(row.sentiment, "~")
        cat  = (row.esg_category or "").ljust(26)
        titl = (row.title or "")[:38]

        sys.stdout.write("[" + str(i).rjust(3) + "/" + str(total) + "]  " + rel + "  [" + icon + "]  " + cat + "  " + titl + "\n")
        sys.stdout.flush()

        if i % 10 == 0:
            session.commit()
            elapsed = round(time.time() - start)
            sys.stdout.write("  --- saved " + str(i) + "/" + str(total) + "  elapsed: " + str(elapsed) + "s ---\n")
            sys.stdout.flush()

    session.commit()

    total_time = round(time.time() - start)
    rel_count  = sum(1 for r in results if r.get("relevant"))
    avg        = round(total_time / total, 1) if total else 0

    print()
    print("=" * 75)
    print("  Done  |  " + str(total) + " articles  |  " + str(rel_count) + " relevant  |  " + str(total_time) + "s  |  avg " + str(avg) + "s/article")
    clf.print_stats()
    print("=" * 75)
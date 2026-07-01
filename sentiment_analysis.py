from __future__ import annotations
"""
sentiment_analysis.py
──────────────────────
Standalone sentiment re-analysis module.
Re-evaluates sentiment for relevant ESG articles already in PostgreSQL
and writes results back, keeping the database the single source of truth.

Usage:
    python sentiment_analysis.py              # analyze articles with missing/neutral sentiment
    python sentiment_analysis.py --all         # re-analyze every relevant article
    python sentiment_analysis.py --limit 50
"""

import argparse, re, requests, os, sys, time
from dotenv import load_dotenv
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
PREFERRED_MODELS = ["qwen2.5:1.5b", "qwen2.5:3b", "phi3.5:latest"]

SENTIMENT_PROMPT = """Read this ESG news headline and content. Decide the overall sentiment for a business reader.

positive = good news: achievement, investment, growth, approval, partnership, target met
negative = bad news: fine, lawsuit, scandal, failure, damage, criticism, delay
neutral = purely factual with no clear winner or loser (use rarely)

Title: {{TITLE}}
Content: {{CONTENT}}

Reply with ONLY one word: positive, negative, or neutral"""


def get_model():
    try:
        r = requests.get(OLLAMA_HOST + "/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        for p in PREFERRED_MODELS:
            if p in models: return p
        return models[0] if models else None
    except Exception:
        return None


def analyze_sentiment(model: str, title: str, body: str) -> str:
    content = (body or "")[:300]
    prompt  = SENTIMENT_PROMPT.replace("{{TITLE}}", (title or "")[:150]).replace("{{CONTENT}}", content)
    try:
        resp = requests.post(
            OLLAMA_HOST + "/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "think": False,
                  "options": {"temperature": 0.1, "num_predict": 10}},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").lower()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        if "positive" in raw: return "positive"
        if "negative" in raw: return "negative"
        return "neutral"
    except Exception:
        return "neutral"


def keyword_sentiment(title: str, body: str) -> str:
    text = (title + " " + (body or "")).lower()
    pos = ["progress","milestone","achieve","invest","launch","approve","record","success",
           "growth","expand","partnership","award","certif","commit","grant","exceed","win"]
    neg = ["fail","scandal","miss","fine","penalt","breach","damage","crisis","setback","greenwash",
           "lawsuit","sue","violat","cancel","delay","layoff","spill","leak","protest","criticism"]
    if any(w in text for w in pos): return "positive"
    if any(w in text for w in neg): return "negative"
    return "neutral"


def main():
    parser = argparse.ArgumentParser(description="ESG Sentiment Analyzer")
    parser.add_argument("--all",   action="store_true", help="re-analyze every relevant article")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    from src.components.database import PostgreSQLStorage
    from src.components.models import ESGArticle
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    db    = PostgreSQLStorage()
    model = get_model()
    use_ollama = model is not None

    print("Sentiment Analyzer  |  Model: " + (model or "keyword fallback"))
    print("=" * 60)

    with Session(db._engine) as session:
        q = select(ESGArticle).where(ESGArticle.relevant == True)
        if not args.all:
            q = q.where((ESGArticle.sentiment == None) | (ESGArticle.sentiment == "unknown"))
        rows = session.scalars(q.limit(args.limit)).all()

        if not rows:
            print("No articles need sentiment analysis.")
            return

        print("Analyzing " + str(len(rows)) + " articles...\n")
        start = time.time()
        counts = {"positive": 0, "negative": 0, "neutral": 0}

        for i, row in enumerate(rows, 1):
            if use_ollama:
                sentiment = analyze_sentiment(model, row.title or "", row.body_text or "")
            else:
                sentiment = keyword_sentiment(row.title or "", row.body_text or "")

            row.sentiment = sentiment
            counts[sentiment] += 1

            icon = {"positive": "+", "negative": "-", "neutral": "~"}[sentiment]
            sys.stdout.write("[" + str(i).rjust(3) + "/" + str(len(rows)) + "]  [" + icon + "]  " + (row.title or "")[:60] + "\n")
            sys.stdout.flush()

            if i % 20 == 0:
                session.commit()
                print("  --- saved " + str(i) + "/" + str(len(rows)) + " ---")

        session.commit()
        elapsed = round(time.time() - start)

    print("\n" + "=" * 60)
    print("Done  |  " + str(len(rows)) + " analyzed  |  " + str(elapsed) + "s")
    print("Positive: " + str(counts["positive"]) + "  Negative: " + str(counts["negative"]) + "  Neutral: " + str(counts["neutral"]))
    print("=" * 60)


if __name__ == "__main__":
    main()
from __future__ import annotations
import argparse, sys, yaml, time
from src.components.ollama_classifier import OllamaClassifier, MAX_WORKERS
from src.components.database import PostgreSQLStorage
from src.components.scraper import ESGScraper, FeedConfig
from src.exception import ConfigError, StorageError
from src.logger import get_logger

log = get_logger("main")


def load_feeds(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        log.error("config not found: " + path); sys.exit(1)
    return [
        FeedConfig(
            name            = fd["name"],
            url             = fd["rss_url"],
            use_browser     = fd.get("use_browser", False),
            use_stealth     = fd.get("use_stealth", False),
            fetch_full_text = fd.get("fetch_full_text", False),
        )
        for fd in data.get("feeds", [])
    ]


def print_summary(db):
    s = db.summary()
    print("\n" + "=" * 70)
    print("  ESG UPDATES  |  Total: " + str(s.get("total",0)) + "  |  Relevant: " + str(s.get("relevant",0)))
    print("=" * 70)
    for section, key in [("By Category","by_category"),("By Sentiment","by_sentiment"),("By Source","by_source")]:
        data = s.get(key, {})
        if data:
            print("\n  " + section)
            for k, v in list(data.items())[:10]:
                print("    " + (k or "").ljust(34) + str(v).rjust(4) + "  " + "#" * min(v, 30))
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",      default="config/sources.yaml")
    parser.add_argument("--no-classify", action="store_true")
    parser.add_argument("--stream",      action="store_true")
    parser.add_argument("--limit",       type=int, default=None)
    parser.add_argument("--export-logs", action="store_true")
    args = parser.parse_args()

    if args.export_logs:
        from src.logger import export_logs_json
        print("logs exported -> " + export_logs_json()); sys.exit(0)

    log.info("ESG Updates pipeline starting")

    # 1. scrape
    feeds = load_feeds(args.config)
    log.info(str(len(feeds)) + " feeds  ("
        + str(sum(1 for f in feeds if not f.use_browser and not f.use_stealth)) + " requests / "
        + str(sum(1 for f in feeds if f.use_browser)) + " browser / "
        + str(sum(1 for f in feeds if f.use_stealth)) + " stealth)")

    articles = ESGScraper(feeds).run()
    if args.limit:
        articles = articles[:args.limit]
    if not articles:
        log.warning("no articles scraped"); sys.exit(0)

    # 2. classify — all inference logic lives in OllamaClassifier
    if not args.no_classify:
        clf = OllamaClassifier()
        clf.load()
        mode = "stream" if args.stream else ("ollama[" + str(clf._model) + "] workers=" + str(MAX_WORKERS) if clf.ready else "keyword fallback")
        log.info("classifying " + str(len(articles)) + " articles via " + mode)

        start = time.time()

        if args.stream:
            # stream mode — one at a time with live output
            rel = 0
            for i, article in enumerate(articles, 1):
                sys.stdout.write("[" + str(i).rjust(3) + "/" + str(len(articles)) + "]  " + (article.title or "")[:60] + "\n")
                sys.stdout.flush()
                r = clf.classify_stream(article.title or "", article.body_text or "")
                _apply(article, r)
                if article.relevant: rel += 1
        else:
            # concurrent batch mode
            article_dicts = [{"title": a.title or "", "body": a.body_text or ""} for a in articles]
            results       = clf.classify_batch(article_dicts)
            rel = 0
            for article, r in zip(articles, results):
                _apply(article, r)
                if article.relevant: rel += 1

        elapsed = round(time.time() - start)
        log.info("classification done  " + str(rel) + "/" + str(len(articles)) + " relevant  " + str(elapsed) + "s")
        clf.print_stats()

    # 3. save
    try:
        db       = PostgreSQLStorage()
        inserted = db.save(articles)
    except (StorageError, ConfigError) as e:
        log.error(str(e)); sys.exit(1)

    # 4. cleanup
    db.delete_old_articles(days=7)
    print_summary(db)
    log.info("pipeline done  scraped=" + str(len(articles)) + "  saved=" + str(inserted))


def _apply(article, r: dict) -> None:
    """Apply classification result to article object. Main thread only."""
    article.esg_category   = r.get("category", "Irrelevant")
    article.confidence     = r.get("confidence", 0.0)
    article.relevant       = r.get("relevant", False)
    article.priority       = "none"
    article.sentiment      = r.get("sentiment", "neutral")
    article.action         = r.get("action", "No action.")
    article.reason         = r.get("reason", "")
    article.primary_fields = r.get("primary_fields", "")
    article.entities       = r.get("entities", "{}")
    article.tags           = r.get("tags", "")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log.exception("fatal: " + str(e)); sys.exit(1)
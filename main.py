import argparse
import sys

import yaml

from src.components.classifier import HuggingFaceClassifier, KeywordClassifier
from src.components.database import PostgreSQLStorage
from src.components.scraper import ESGScraper, FeedConfig
from src.exception import ConfigError, StorageError
from src.logger import export_logs_json, get_logger

log = get_logger("main")


def load_feeds(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        log.error(f"config file not found: {path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        log.error(f"bad yaml in {path}: {e}")
        sys.exit(1)

    feeds = data.get("feeds", [])
    if not feeds:
        log.error("no feeds defined in sources.yaml")
        sys.exit(1)

    return [
        FeedConfig(
            name=fd["name"],
            url=fd["rss_url"],
            use_browser=fd.get("use_browser", False),
            fetch_full_text=fd.get("fetch_full_text", False),
        )
        for fd in feeds
    ]


def print_summary(db: PostgreSQLStorage):
    stats = db.summary()
    recent = db.recent(10)

    print("")
    print("-" * 70)
    print(f"  ESG INTEL  |  articles in db: {stats['total']}")
    print("-" * 70)

    print("")
    print("  by source")
    for src, cnt in stats["by_source"].items():
        bar = "#" * min(cnt, 30)
        print(f"    {src:<32}  {cnt:>4}  {bar}")

    print("")
    print("  by esg category")
    for cat, cnt in stats["by_category"].items():
        bar = "#" * min(cnt, 30)
        print(f"    {cat:<18}  {cnt:>4}  {bar}")

    print("")
    print("  fetched via")
    for method, cnt in stats["by_method"].items():
        if method is None:
            method = "unknown"
        print(f"    {method:<12}  {cnt:>4}")

    print("")
    print("  10 most recent")
    for i, row in enumerate(recent, 1):
        date = (row["date"] or "")[:10]
        cat = (row["category"] or "-")[:13]
        conf = f"{row['confidence']:.0%}" if row["confidence"] else " -"
        src = (row["source"] or "")[:20]
        title = (row["title"] or "")[:46]
        print(f"  {i:>2}.  [{date}]  {cat:<13}  {conf:>4}  {title}  ({src})")

    print("-" * 70)
    print("")


def main():
    parser = argparse.ArgumentParser(description="ESG Intel v4 pipeline")
    parser.add_argument("--config", default="config/sources.yaml")
    parser.add_argument("--mode", choices=["hf", "keyword"], default="hf")
    parser.add_argument("--no-classify", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--export-logs", action="store_true")
    args = parser.parse_args()

    if args.export_logs:
        path = export_logs_json()
        print(f"logs exported to {path}")
        sys.exit(0)

    log.info("ESG Intel v4 starting")

    feeds = load_feeds(args.config)
    browser_feeds = [f for f in feeds if f.use_browser]
    requests_feeds = [f for f in feeds if not f.use_browser]
    log.info(f"{len(feeds)} feeds loaded  ({len(requests_feeds)} requests / {len(browser_feeds)} browser)")

    scraper = ESGScraper(feeds)
    articles = scraper.run()

    if args.limit:
        articles = articles[:args.limit]
        log.info(f"capped at {args.limit} articles")

    if not articles:
        log.warning("no fresh articles found")
        sys.exit(0)

    if not args.no_classify:
        clf = KeywordClassifier() if args.mode == "keyword" else HuggingFaceClassifier()
        clf.load()
        labels = clf.classify_batch([a.text_for_classifier() for a in articles])
        for article, result in zip(articles, labels):
            article.esg_category = result["category"]
            article.confidence = result["confidence"]
        log.info(f"classification done - {len(articles)} articles labelled")

    try:
        db = PostgreSQLStorage()
        inserted = db.save(articles)
    except (StorageError, ConfigError) as e:
        log.error(str(e))
        sys.exit(1)

    print_summary(db)
    log.info(f"pipeline done - scraped {len(articles)} | new in db {inserted}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log.exception(f"fatal: {e}")
        sys.exit(1)

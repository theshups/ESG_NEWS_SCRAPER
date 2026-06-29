from __future__ import annotations
"""
trend_synthesis.py
──────────────────
Sprint 3 — Trend Synthesis Engine

Pulls all articles from the past 7 days grouped by category,
feeds aggregated context to Ollama, and generates a
"Top 5 Emerging ESG Trends" intelligence report.

Usage:
    python trend_synthesis.py
    python trend_synthesis.py --days 14
    python trend_synthesis.py --output report.html
"""

import argparse, os, re, requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dotenv import load_dotenv
from src.components.database import PostgreSQLStorage
from src.components.models import ESGArticle
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

TREND_PROMPT = """/no_think
You are a senior ESG analyst preparing a weekly intelligence briefing for a carbon management and sustainability consulting firm.

The firm specialises in:
- BRSR and BRSR Core reporting for Indian companies
- EU CBAM compliance
- Corporate carbon footprints (Scope 1, 2, 3)
- Net zero transition planning
- CSRD and ISSB sustainability disclosure
- Carbon markets and credits
- Supply chain due diligence

Below are ESG news articles from the past {{DAYS}} days, grouped by category.

{{ARTICLES}}

Based on this news, write a professional intelligence report with exactly this structure:

EXECUTIVE SUMMARY
2-3 sentences summarising the most important ESG developments this week.

TOP 5 EMERGING TRENDS

Trend 1: [Title]
[2-3 sentences explaining the trend, which companies or regulators are involved, and what it means for ESG compliance and carbon management]

Trend 2: [Title]
[2-3 sentences]

Trend 3: [Title]
[2-3 sentences]

Trend 4: [Title]
[2-3 sentences]

Trend 5: [Title]
[2-3 sentences]

KEY REGULATORY DEADLINES
List any regulatory deadlines or compliance dates mentioned in the articles.

RECOMMENDED ACTIONS
3 specific actions businesses should take this week based on the news above.

SENTIMENT OVERVIEW
Overall market sentiment: positive / negative / neutral
Brief explanation in 1-2 sentences."""


def get_model():
    try:
        r = requests.get(OLLAMA_HOST + "/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        for p in ["qwen2.5:1.5b","phi3.5:latest","qwen2.5:3b"]:
            if p in models: return p
        return models[0] if models else None
    except Exception:
        return None


def fetch_articles(days: int = 7) -> dict:
    """Fetch articles grouped by category from the past N days."""
    db      = PostgreSQLStorage()
    cutoff  = datetime.now(timezone.utc) - timedelta(days=days)
    grouped = defaultdict(list)

    with Session(db._engine) as session:
        rows = session.scalars(
            select(ESGArticle)
            .where(ESGArticle.published_date >= cutoff)
            .where(ESGArticle.relevant == True)
            .where(ESGArticle.esg_category != None)
            .where(ESGArticle.esg_category != "Irrelevant")
            .order_by(ESGArticle.published_date.desc())
        ).all()

        for row in rows:
            cat = row.esg_category or "Uncategorised"
            grouped[cat].append({
                "title":     row.title or "",
                "source":    row.source_name or "",
                "date":      row.published_date.strftime("%d %b %Y") if row.published_date else "",
                "sentiment": row.sentiment or "neutral",
                "action":    row.action or "",
                "body":      (row.body_text or "")[:300],
            })

    return dict(grouped)


def build_context(grouped: dict, max_per_cat: int = 5) -> str:
    """Build article context string for the prompt."""
    lines = []
    for cat, articles in sorted(grouped.items()):
        lines.append("\n--- " + cat.replace("_"," ") + " (" + str(len(articles)) + " articles) ---")
        for a in articles[:max_per_cat]:
            lines.append("• [" + a["date"] + "] [" + a["sentiment"] + "] " + a["title"] + " (" + a["source"] + ")")
            if a["body"]:
                lines.append("  " + a["body"][:200])
    return "\n".join(lines)


def generate_report(context: str, days: int, model: str) -> str:
    """Call Ollama to generate the trend report."""
    prompt = TREND_PROMPT.replace("{{DAYS}}", str(days)).replace("{{ARTICLES}}", context)
    print("Generating trend report with " + model + "...")
    print("This may take 2-3 minutes...")

    try:
        resp = requests.post(
            OLLAMA_HOST + "/api/generate",
            json={
                "model":  model,
                "prompt": prompt,
                "stream": False,
                "think":  False,
                "options": {"temperature": 0.4, "num_predict": 1200},
            },
            timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"</?think>", "", raw).strip()
        return raw
    except Exception as e:
        return "Report generation failed: " + str(e)


def format_html(report: str, grouped: dict, days: int) -> str:
    """Format the report as clean HTML."""
    now       = datetime.now().strftime("%d %B %Y, %H:%M")
    total_art = sum(len(v) for v in grouped.values())

    cat_rows = ""
    for cat, arts in sorted(grouped.items()):
        pos = sum(1 for a in arts if a["sentiment"]=="positive")
        neg = sum(1 for a in arts if a["sentiment"]=="negative")
        neu = len(arts) - pos - neg
        cat_rows += (
            "<tr><td style='padding:8px 12px;border-bottom:1px solid #e2e8f0'>" + cat.replace("_"," ") + "</td>"
            + "<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:center'>" + str(len(arts)) + "</td>"
            + "<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#16a34a;text-align:center'>" + str(pos) + "</td>"
            + "<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#dc2626;text-align:center'>" + str(neg) + "</td>"
            + "<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;text-align:center'>" + str(neu) + "</td>"
            + "</tr>"
        )

    report_html = ""
    for line in report.split("\n"):
        line = line.strip()
        if not line:
            report_html += "<br/>"
        elif line.startswith("EXECUTIVE SUMMARY") or line.startswith("TOP 5") or line.startswith("KEY REGULATORY") or line.startswith("RECOMMENDED") or line.startswith("SENTIMENT"):
            report_html += "<h3 style='color:#064e3b;margin:20px 0 8px;font-size:14px;text-transform:uppercase;letter-spacing:.08em'>" + line + "</h3>"
        elif line.startswith("Trend "):
            report_html += "<h4 style='color:#0f172a;margin:14px 0 4px;font-size:13px;font-weight:600'>" + line + "</h4>"
        elif line.startswith("•") or line.startswith("-"):
            report_html += "<p style='margin:4px 0;color:#475569;font-size:13px;padding-left:16px'>" + line + "</p>"
        else:
            report_html += "<p style='margin:6px 0;color:#334155;font-size:13px;line-height:1.6'>" + line + "</p>"

    return """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<title>ESG Intelligence Report — """ + now + """</title>
</head>
<body style="font-family:'Inter',Arial,sans-serif;background:#f8fafc;margin:0;padding:20px">
<div style="max-width:700px;margin:0 auto">

  <!-- header -->
  <div style="background:#064e3b;border-radius:12px 12px 0 0;padding:28px 32px">
    <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700">ESG Updates</h1>
    <p style="color:rgba(255,255,255,.7);margin:4px 0 0;font-size:12px">Weekly Intelligence Report &nbsp;·&nbsp; """ + now + """</p>
  </div>

  <!-- summary stats -->
  <div style="background:#fff;padding:20px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">
    <p style="color:#64748b;font-size:12px;margin:0 0 16px">Coverage: last """ + str(days) + """ days &nbsp;·&nbsp; """ + str(total_art) + """ relevant articles &nbsp;·&nbsp; """ + str(len(grouped)) + """ categories</p>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f1f5f9">
          <th style="padding:8px 12px;text-align:left;color:#64748b;font-weight:600">Category</th>
          <th style="padding:8px 12px;text-align:center;color:#64748b;font-weight:600">Articles</th>
          <th style="padding:8px 12px;text-align:center;color:#16a34a;font-weight:600">Positive</th>
          <th style="padding:8px 12px;text-align:center;color:#dc2626;font-weight:600">Negative</th>
          <th style="padding:8px 12px;text-align:center;color:#64748b;font-weight:600">Neutral</th>
        </tr>
      </thead>
      <tbody>""" + cat_rows + """</tbody>
    </table>
  </div>

  <!-- ai report -->
  <div style="background:#fff;padding:24px 32px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px">
    <div style="background:#f0fdf4;border-left:4px solid #064e3b;border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:20px">
      <p style="color:#064e3b;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin:0 0 4px">AI Generated Analysis</p>
      <p style="color:#475569;font-size:11px;margin:0">Generated by local AI model. Always verify with source articles.</p>
    </div>
    """ + report_html + """
  </div>

  <!-- footer -->
  <div style="text-align:center;padding:20px;color:#94a3b8;font-size:11px">
    ESG Updates &nbsp;·&nbsp; Sustainability &amp; Carbon Intelligence &nbsp;·&nbsp; """ + now + """
  </div>

</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="ESG Trend Synthesis Report")
    parser.add_argument("--days",   type=int, default=7,           help="days to look back")
    parser.add_argument("--output", type=str, default="",          help="output HTML file")
    parser.add_argument("--text",   action="store_true",           help="print text report only")
    args = parser.parse_args()

    print("\nESG Trend Synthesis — last " + str(args.days) + " days")
    print("=" * 55)

    # 1. fetch articles
    grouped = fetch_articles(args.days)
    total   = sum(len(v) for v in grouped.values())

    if not grouped:
        print("No relevant articles found. Run make scrape first.")
        return

    print("Found " + str(total) + " relevant articles across " + str(len(grouped)) + " categories")
    for cat, arts in sorted(grouped.items()):
        print("  " + cat.replace("_"," ").ljust(32) + str(len(arts)))

    # 2. get model
    model = get_model()
    if not model:
        print("Ollama not running. Start Ollama first.")
        return

    # 3. build context and generate
    context = build_context(grouped)
    report  = generate_report(context, args.days, model)

    if args.text:
        print("\n" + report)
        return

    # 4. format and save
    import os as _os
    out = args.output or ("esg_trend_report_" + datetime.now().strftime("%Y%m%d") + ".html")
    html = format_html(report, grouped, args.days)

    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print("\nReport saved: " + out)
    print("Open in browser to view the formatted report.")


if __name__ == "__main__":
    main()
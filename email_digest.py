from __future__ import annotations
"""
email_digest.py
───────────────
Sprint 3 — HTML Email Digest

Generates a clean HTML email digest of the latest ESG news.
Can be sent via SMTP or saved as HTML file.

Usage:
    python email_digest.py                    # save HTML only
    python email_digest.py --send             # send via SMTP
    python email_digest.py --days 3           # last 3 days
"""

import argparse, os, smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

CAT_COLORS = {
    "BRSR":                      "#f97316",
    "CBAM":                      "#3b82f6",
    "Carbon_Accounting":         "#14b8a6",
    "Decarbonization":           "#10b981",
    "Sustainability_Disclosure": "#8b5cf6",
    "Environmental_Regulation":  "#f43f5e",
    "Supply_Chain_Due_Diligence":"#6366f1",
    "Governance_Compliance":     "#7c3aed",
    "Material_ESG_Risk":         "#e11d48",
    "Carbon_Markets":            "#059669",
}

SENT_COLORS = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#64748b"}
SENT_ICONS  = {"positive": "+", "negative": "-", "neutral": "~"}


def fetch_digest_articles(days: int = 1):
    from src.components.database import PostgreSQLStorage
    from src.components.models import ESGArticle
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    db     = PostgreSQLStorage()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
            grouped[row.esg_category or "Other"].append({
                "title":    row.title or "",
                "url":      row.url or "#",
                "source":   row.source_name or "",
                "date":     row.published_date.strftime("%d %b %Y") if row.published_date else "",
                "sentiment":row.sentiment or "neutral",
                "action":   row.action or "",
                "reason":   row.reason or "",
                "tags":     row.tags or "",
            })

    return dict(grouped)


def render_html(grouped: dict, days: int) -> str:
    now   = datetime.now().strftime("%d %B %Y")
    total = sum(len(v) for v in grouped.values())

    if not grouped:
        return "<p>No articles found for the past " + str(days) + " days.</p>"

    sections = ""
    for cat, articles in sorted(grouped.items()):
        color = CAT_COLORS.get(cat, "#64748b")
        cat_label = cat.replace("_", " ")

        article_rows = ""
        for a in articles[:8]:
            sc = SENT_COLORS.get(a["sentiment"], "#64748b")
            si = SENT_ICONS.get(a["sentiment"], "~")
            tags_html = ""
            if a["tags"]:
                tags = [t.strip() for t in a["tags"].split(",") if t.strip()][:3]
                tags_html = " ".join(
                    "<span style='background:#f1f5f9;color:#64748b;font-size:10px;padding:2px 6px;border-radius:3px;margin-right:3px'>" + t + "</span>"
                    for t in tags
                )

            article_rows += """
            <tr>
              <td style="padding:12px 0;border-bottom:1px solid #f1f5f9;vertical-align:top">
                <div style="display:flex;align-items:flex-start;gap:10px">
                  <span style="color:""" + sc + """;font-weight:700;font-size:11px;flex-shrink:0;margin-top:2px">[""" + si + """]</span>
                  <div>
                    <a href='""" + a["url"] + """' style="color:#0f172a;font-weight:600;font-size:13px;text-decoration:none;line-height:1.4;display:block">""" + a["title"][:100] + """</a>
                    <p style="color:#64748b;font-size:11px;margin:3px 0">""" + a["source"] + """ &nbsp;·&nbsp; """ + a["date"] + """</p>
                    """ + ("""<p style="color:#065f46;font-size:11px;margin:3px 0;font-style:italic">→ """ + a["action"] + """</p>""" if a["action"] and a["action"] != "No action." else "") + """
                    """ + ("""<div style="margin-top:4px">""" + tags_html + """</div>""" if tags_html else "") + """
                  </div>
                </div>
              </td>
            </tr>"""

        sections += """
        <div style="margin-bottom:28px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid """ + color + """">
            <span style="background:""" + color + """;color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:999px;text-transform:uppercase;letter-spacing:.06em">""" + cat_label + """</span>
            <span style="color:#94a3b8;font-size:11px">""" + str(len(articles)) + """ articles</span>
          </div>
          <table style="width:100%;border-collapse:collapse">""" + article_rows + """</table>
          """ + ("""<p style="color:#94a3b8;font-size:11px;margin-top:6px">+ """ + str(len(articles)-8) + """ more articles in this category</p>""" if len(articles) > 8 else "") + """
        </div>"""

    return """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/><title>ESG Updates Digest — """ + now + """</title></head>
<body style="font-family:'Inter',Arial,sans-serif;background:#f8fafc;margin:0;padding:20px">
<div style="max-width:680px;margin:0 auto">

  <div style="background:#064e3b;border-radius:12px 12px 0 0;padding:28px 32px">
    <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;letter-spacing:-.3px">ESG Updates</h1>
    <p style="color:rgba(255,255,255,.7);margin:4px 0 0;font-size:12px;letter-spacing:.05em">DAILY INTELLIGENCE DIGEST &nbsp;·&nbsp; """ + now + """</p>
  </div>

  <div style="background:#fff;padding:20px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:4px">
      <div style="text-align:center;background:#f0fdf4;border-radius:8px;padding:12px">
        <div style="font-size:24px;font-weight:700;color:#064e3b">""" + str(total) + """</div>
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Relevant Articles</div>
      </div>
      <div style="text-align:center;background:#f0fdf4;border-radius:8px;padding:12px">
        <div style="font-size:24px;font-weight:700;color:#064e3b">""" + str(len(grouped)) + """</div>
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Categories</div>
      </div>
      <div style="text-align:center;background:#f0fdf4;border-radius:8px;padding:12px">
        <div style="font-size:24px;font-weight:700;color:#064e3b">""" + str(days) + """d</div>
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Coverage</div>
      </div>
    </div>
  </div>

  <div style="background:#fff;padding:24px 32px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px">
    """ + sections + """
  </div>

  <div style="text-align:center;padding:20px;color:#94a3b8;font-size:11px">
    ESG Updates &nbsp;·&nbsp; Sustainability &amp; Carbon Intelligence<br/>
    <a href="http://localhost:8000" style="color:#064e3b">View full dashboard</a>
  </div>

</div>
</body>
</html>"""


def send_email(html: str, subject: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    to_email  = os.getenv("DIGEST_TO",  "")

    if not all([smtp_user, smtp_pass, to_email]):
        print("SMTP not configured. Add SMTP_USER, SMTP_PASS, DIGEST_TO to .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, to_email, msg.as_string())
        print("Email sent to " + to_email)
        return True
    except Exception as e:
        print("Email failed: " + str(e))
        return False


def main():
    parser = argparse.ArgumentParser(description="ESG Email Digest")
    parser.add_argument("--days",   type=int,  default=1,     help="days to cover")
    parser.add_argument("--send",   action="store_true",      help="send via SMTP")
    parser.add_argument("--output", type=str,  default="",    help="output file")
    args = parser.parse_args()

    print("ESG Email Digest — last " + str(args.days) + " day(s)")
    grouped = fetch_digest_articles(args.days)
    total   = sum(len(v) for v in grouped.values())

    if not grouped:
        print("No relevant articles found. Run make scrape first.")
        return

    print("Found " + str(total) + " articles across " + str(len(grouped)) + " categories")

    html    = render_html(grouped, args.days)
    now_str = datetime.now().strftime("%Y%m%d")
    out     = args.output or ("esg_digest_" + now_str + ".html")

    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("Digest saved: " + out)

    if args.send:
        subject = "ESG Updates Digest — " + datetime.now().strftime("%d %B %Y")
        send_email(html, subject)


if __name__ == "__main__":
    main()
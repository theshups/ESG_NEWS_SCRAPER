from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from src.components.database import PostgreSQLStorage
from src.components.summarizer import Summarizer

app       = FastAPI(title="ESG Updates")
templates = Jinja2Templates(directory="api/templates")

_s = Summarizer()
_s.load()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(content=templates.get_template("index.html").render())


@app.get("/health")
async def health():
    return {"status": "ok", "model_ready": _s.ready}


@app.get("/api/articles")
async def articles(category: str = None, sentiment: str = None, limit: int = 500):
    try:
        db = PostgreSQLStorage()
        if category and category != "All":
            return db.get_by_category(category, limit)
        return db.recent(limit, relevant_only=True)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/summary/{article_id}")
async def summary(article_id: str):
    try:
        db = PostgreSQLStorage()
        cached = db.get_summary(article_id)
        if cached:
            return {"summary": cached, "source": "cache"}
        if not _s.ready:
            return {"summary": "", "source": "model_loading", "message": "Model still loading, try again shortly."}
        article = db.get_by_id(article_id)
        if not article:
            return {"summary": "", "source": "not_found"}
        result = _s.summarize(article.get("title",""), article.get("body_text",""))
        if result:
            db.save_summary(article_id, result)
            return {"summary": result, "source": "local"}
        return {"summary": "", "source": "failed", "message": "Could not generate summary."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/stats")
async def stats():
    try:
        return PostgreSQLStorage().summary()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/trend-report")
async def trend_report(days: int = 7):
    try:
        import sys, os as _os
        sys.path.insert(0, _os.getcwd())
        from trend_synthesis import fetch_articles, build_context, generate_report, get_model
        grouped = fetch_articles(days)
        if not grouped:
            return {"report": "No relevant articles found for this period.", "categories": {}}
        model = get_model()
        if not model:
            return JSONResponse(status_code=503, content={"error": "Ollama not available"})
        context = build_context(grouped)
        report  = generate_report(context, days, model)
        return {"report": report, "categories": {k: len(v) for k, v in grouped.items()}}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/digest-html")
async def digest_html(days: int = 1):
    try:
        import sys, os as _os
        sys.path.insert(0, _os.getcwd())
        from email_digest import fetch_digest_articles, render_html
        grouped = fetch_digest_articles(days)
        html = render_html(grouped, days)
        return HTMLResponse(content=html)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    return {"status": "ok", "summarizer": _s.ready}


@app.get("/api/articles")
async def articles(category: str = None, priority: str = None, relevant_only: bool = False, limit: int = 500):
    try:
        db = PostgreSQLStorage()
        if category and category != "All":
            return db.get_by_category(category, limit)
        if priority and priority != "All":
            return db.get_by_priority(priority, limit)
        return db.recent(limit, relevant_only=False)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/summary/{article_id}")
async def summary(article_id: str):
    try:
        db     = PostgreSQLStorage()
        cached = db.get_summary(article_id)
        if cached:
            return {"summary": cached, "source": "cache"}
        if not _s.ready:
            return {"summary": "", "source": "model_loading",
                    "message": "Summarizer still loading. Try again in a moment."}
        article = db.get_by_id(article_id)
        if not article:
            return {"summary": "", "source": "not_found"}
        result = _s.summarize(article.get("title", ""), article.get("body_text", ""))
        if result:
            db.save_summary(article_id, result)
        return {"summary": result, "source": "local"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/stats")
async def stats():
    try:
        return PostgreSQLStorage().summary()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
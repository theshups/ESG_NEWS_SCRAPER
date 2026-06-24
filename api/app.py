from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.components.database import PostgreSQLStorage
from src.components.summarizer import GeminiSummarizer

app        = FastAPI(title="ESG Intel")
templates  = Jinja2Templates(directory="api/templates")
summarizer = GeminiSummarizer()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    template = templates.get_template("index.html")
    html = template.render()
    return HTMLResponse(content=html)


@app.get("/api/articles")
async def get_articles(category: str = None, limit: int = 50):
    try:
        db = PostgreSQLStorage()
        if category and category != "All":
            return db.get_by_category(category, limit)
        return db.recent(limit)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/summary/{article_id}")
async def get_summary(article_id: str):
    try:
        db = PostgreSQLStorage()
        cached = db.get_summary(article_id)
        if cached:
            return {"summary": cached, "source": "cache"}
        article = db.get_by_id(article_id)
        if not article:
            return {"summary": "", "source": "none"}
        summary = summarizer.summarize(
            article.get("title", ""),
            article.get("body_text", ""),
        )
        if summary:
            db.save_summary(article_id, summary)
        return {"summary": summary, "source": "gemini"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/stats")
async def get_stats():
    try:
        db = PostgreSQLStorage()
        return db.summary()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
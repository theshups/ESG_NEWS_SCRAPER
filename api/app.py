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

# load model at startup — blocks until ready, ensures no race condition
_s = Summarizer()
_s.load()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(content=templates.get_template("index.html").render())


@app.get("/health")
async def health():
    return {"status": "ok", "model_ready": _s.ready}


@app.get("/api/articles")
async def articles(category: str = None, limit: int = 60):
    try:
        db = PostgreSQLStorage()
        return db.get_by_category(category, limit) if (category and category != "All") else db.recent(limit)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/summary/{article_id}")
async def summary(article_id: str):
    try:
        db = PostgreSQLStorage()

        # serve cached summary immediately
        cached = db.get_summary(article_id)
        if cached:
            return {"summary": cached, "source": "cache", "ready": True}

        if not _s.ready:
            return {"summary": "", "source": "model_loading", "ready": False,
                    "message": "Model is still loading. Please try again in a moment."}

        article = db.get_by_id(article_id)
        if not article:
            return {"summary": "", "source": "not_found", "ready": True}

        result = _s.summarize(
            article.get("title", ""),
            article.get("body_text", ""),
        )

        if result:
            db.save_summary(article_id, result)
            return {"summary": result, "source": "local", "ready": True}

        return {"summary": "", "source": "failed", "ready": True,
                "message": "Could not generate summary for this article."}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/stats")
async def stats():
    try:
        return PostgreSQLStorage().summary()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
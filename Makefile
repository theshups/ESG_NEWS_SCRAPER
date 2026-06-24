# ESG Updates - Docker Task Runner
# Usage: make <command>
# Requires: make for Windows (winget install GnuWin32.Make)

.PHONY: build run stop restart logs scrape frontend shell clean rebuild health

# ── Docker ────────────────────────────────────────────────────
build:
    docker-compose build

run:
    docker-compose up -d
    @echo "App running at http://localhost:8000"

stop:
    docker-compose down

restart:
    docker-compose down
    docker-compose up -d

rebuild:
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d

logs:
    docker-compose logs -f app

logs-db:
    docker-compose logs -f postgres

# ── Pipeline ──────────────────────────────────────────────────
scrape:
    docker-compose exec app python main.py --mode keyword

scrape-hf:
    docker-compose exec app python main.py --mode hf

evaluate:
    docker-compose exec app python evaluate.py

export-logs:
    docker-compose exec app python main.py --export-logs

# ── Dev ───────────────────────────────────────────────────────
frontend:
    uvicorn api.app:app --reload --port 8000

shell:
    docker-compose exec app bash

db-shell:
    docker-compose exec postgres psql -U postgres -d esg_intel

# ── Health ────────────────────────────────────────────────────
health:
    curl -s http://localhost:8000/health || echo "App not responding"

status:
    docker-compose ps

# ── Cleanup ───────────────────────────────────────────────────
clean:
    docker-compose down -v
    docker system prune -f

clean-logs:
    del /Q logs\*.log logs\*.jsonl 2>nul || true
FROM python:3.11-slim

WORKDIR /app

# system packages needed by Playwright's Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    wget \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# install python deps first (layer caching — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# install chromium browser for playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# copy project files
COPY . .

# create folders so the app doesn't crash on first run
RUN mkdir -p logs data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# default command — keyword mode works without HuggingFace model download
CMD ["python", "main.py", "--mode", "keyword"]

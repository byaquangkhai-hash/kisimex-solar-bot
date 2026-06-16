FROM python:3.11-slim

WORKDIR /app

# System deps needed before playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright + Chromium with all system deps
RUN playwright install chromium --with-deps

# App code
COPY . .

CMD ["python", "kisimex_report.py"]

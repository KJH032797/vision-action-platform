FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && install -d -o appuser -g appuser /app/private_media
COPY manage.py run-worker.sh ./
COPY config ./config
COPY accounts ./accounts
COPY analyses ./analyses
COPY templates ./templates
USER appuser

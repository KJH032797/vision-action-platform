FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && install -d -o appuser -g appuser /app/private_media
COPY manage.py .
COPY config ./config
COPY accounts ./accounts
COPY analyses ./analyses
COPY templates ./templates
USER appuser
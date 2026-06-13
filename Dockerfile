# Supervisor service (FastAPI) — the public delegation brain + phone reply page.
# Deployed to Railway; sivra.io points here.
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY supervisor ./supervisor
COPY delivery ./delivery
COPY config ./config

EXPOSE 8000
CMD ["sh", "-c", "uvicorn supervisor.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

# retrain_cron — the daily delegation-router auto-retrain loop (no GPU).
# Pioneer does the actual fine-tune remotely; this host only builds the dataset,
# drives the API, evals two job-ids, and promotes via the app. CPU-only, light deps
# (the guardrail falls back to regex when gliner2 is absent — see supervisor/guardrail.py).
FROM python:3.11-slim
WORKDIR /app

# Light requirements: fastapi/uvicorn unused here but the shared file is tiny and
# avoids a second requirements file drifting out of sync.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code the loop touches: shared contracts, supervisor (guardrail/router/config),
# pioneer (client/dataset/feedback/retrain/auto_retrain), eval harness, config,
# and the pre-built base SFT + held-out eval set under data/datasets.
COPY shared ./shared
COPY supervisor ./supervisor
COPY config ./config
COPY pioneer ./pioneer
COPY eval ./eval
COPY data/datasets ./data/datasets
COPY retrain_cron ./retrain_cron

# One pass then exit — Railway's cron scheduler re-invokes on schedule.
CMD ["python", "retrain_cron/run.py"]

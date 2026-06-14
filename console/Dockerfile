# sivra · console — FastAPI single-page tester for the live SMS + voice tiers.
# Deployed to Railway as a NEW service ("console") in project believable-comfort.
# It only calls the public HTTP surfaces of the supervisor / voice / Telnyx; no
# heavy deps, no audio stack.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui.py ./

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

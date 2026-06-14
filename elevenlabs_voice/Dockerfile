# sivra Voice — ElevenLabs Conversational AI edition.
# Thin FastAPI service: takes POST /call from the supervisor and starts an
# ElevenLabs ConvAI outbound call (ElevenLabs -> Telnyx SIP -> PSTN). No audio
# stack, no Pipecat — ElevenLabs runs the whole call server-side.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

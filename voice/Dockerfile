# Quartermaster Voice Tier — FastAPI + websocket bridge (Telnyx <-> Gemini Live).
# Deployed to Railway as a NEW service (not "supervisor"). Telnyx connects back
# to this service's public https (/telnyx/voice webhook) and wss (/media stream).
FROM python:3.12-slim

# Pipecat audio stack needs a few system libs (resampling, ONNX runtime, libgomp).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py setup_telnyx_voice.py test_gemini_live.py ./

EXPOSE 8000
# Single worker: in-process CALLS map + websocket bridge must share state.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

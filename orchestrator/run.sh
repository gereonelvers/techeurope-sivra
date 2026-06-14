#!/usr/bin/env bash
# Launch the mission orchestrator (the glue). Reads keys from the repo-root .env.
#
#   ./run.sh                 # serve on :8800
#   PORT=8800 ./run.sh
#
# Then open http://localhost:8800/ , type a goal, hit "Launch mission".
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# load repo-root .env (so SUPERVISOR_URL / SERVE_ENDPOINT / etc. are present for
# the agent loop too). Never prints secrets.
if [ -f "$HERE/../.env" ]; then set -a; source "$HERE/../.env"; set +a; fi

PORT="${PORT:-8800}"
exec "$HERE/.venv/bin/uvicorn" app:app --host 0.0.0.0 --port "$PORT"

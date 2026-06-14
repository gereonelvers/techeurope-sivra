# sivra · mission control — the hero ops dashboard (FastAPI single page).
# Deployed to Railway as a NEW service ("mission-control") in project
# believable-comfort, alongside supervisor / voice / console.
#
# The bundled screenshots (static/shots, ~17 MB of downscaled JPEG) and the
# replay manifest (fleet.json) are produced offline by prep_data.py from the
# recorded buyer trajectories and committed into the image, so the container has
# zero dependency on the 1 GB source corpus or any live infra.
#
# NOTE: the manifest lives at the service root (not in a data/ subdir) on purpose
# — the repo-root .railwayignore excludes any data/ dir from the upload context.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui.py fleet.json ./
COPY static/ ./static/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

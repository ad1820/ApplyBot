FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY supabase ./supabase
COPY config ./config

ENV PYTHONUNBUFFERED=1
# Default port for local `docker run`; platforms like Render inject their
# own $PORT at runtime, which the shell form of CMD below picks up
# automatically (falls back to 8000 if $PORT isn't set).
ENV PORT=8000

EXPOSE 8000

# Shell form (not exec/JSON-array form) so $PORT is expanded at container
# start time - this lets the same image work unmodified on platforms that
# require binding to a platform-assigned port (e.g. Render's $PORT, whose
# default is 10000) as well as plain `docker run -p 8000:8000` locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

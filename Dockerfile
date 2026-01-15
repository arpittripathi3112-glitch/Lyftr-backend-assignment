# ---------- Builder ----------
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ---------- Runtime ----------
FROM python:3.11-slim

# Create non-root user
RUN useradd -m appuser

WORKDIR /app

# Copy installed dependencies to appuser's home
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application
COPY app/ ./app/

# Create data directory & fix permissions
RUN mkdir -p /data && chown -R appuser:appuser /data /app /home/appuser/.local

# Switch to non-root user
USER appuser

# Default port, can be overridden via environment
ENV PORT=8000
EXPOSE ${PORT}

# Default to reload mode, can be overridden via docker-compose or CLI
ENV UVICORN_CMD="--reload"

# Disable uvicorn access logs (we have our own middleware)
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log $UVICORN_CMD

# ── build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Run as non-root for least-privilege posture.
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app/ ./app/

USER appuser

EXPOSE 8000

# Single worker is fine for a demo; bump --workers for production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

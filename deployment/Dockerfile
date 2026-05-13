# ── Stage 1: Builder ────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir build && \
    pip wheel --no-cache-dir --wheel-dir /wheels -e ".[dev]"

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="XAUUSD Trading Platform"
LABEL org.opencontainers.image.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

WORKDIR /app

# Copy only what is needed
COPY --from=builder /wheels /wheels
COPY . /app/

RUN pip install --no-cache-dir --no-index --find-links=/wheels -e . && \
    rm -rf /wheels && \
    mkdir -p logs exports/latest exports/history exports/reports datasets/raw live_logs

# Non-root user
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

EXPOSE 8000
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health', timeout=5)"

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# AIRA-X backend — production image.
# Build context: ./backend   (e.g. `docker build -t aira-x-backend ./backend`)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime libs: libgomp1 for onnxruntime/torch, curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application code.
COPY . .

# Non-root user + writable storage dirs (mount a volume here in production).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p storage/chroma storage/uploads storage/vector_index \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe (the API also exposes /ready for readiness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Secrets come from the environment at runtime — never baked into the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

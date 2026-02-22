FROM python:3.11-slim

LABEL maintainer="OpenClaw Team"
LABEL description="OpenClaw Affiliate Marketing Automation System"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY ops/env/example.env ./.env.template

# Create runtime directories
RUN mkdir -p logs data data/backups

# Non-root user for security
RUN useradd --create-home appuser
RUN chown -R appuser:appuser /app
USER appuser

# Initialize on first start: copy .env template if no .env exists
# then init the database
RUN cp .env.template .env 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -m src.cli health || exit 1

# Default: run in dry-run mode on the core node
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--node-role", "core", "--dry-run", "--max-ticks", "1"]

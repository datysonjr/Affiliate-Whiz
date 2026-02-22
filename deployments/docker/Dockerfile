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

# Create runtime directories
RUN mkdir -p logs tmp data

# Non-root user for security
RUN useradd --create-home appuser
RUN chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python src/cli.py health || exit 1

# Default command
ENTRYPOINT ["python", "src/main.py"]
CMD ["--dry-run"]

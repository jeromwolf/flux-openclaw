# flux-openclaw Docker image
# Multi-stage build with Python 3.11-slim

# Stage 1: Dependencies
FROM python:3.11-slim AS deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Application
FROM python:3.11-slim
WORKDIR /app

# Create non-root user
RUN groupadd -r flux && useradd -r -g flux -d /app flux

# Copy dependencies from build stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY *.py ./
COPY tools/ tools/
COPY marketplace/ marketplace/
COPY memory/ memory/
COPY dashboard/ dashboard/
COPY docs/ docs/
COPY instruction.md ./

# Create data directories with correct ownership
RUN mkdir -p data logs backups memory knowledge scheduler && \
    chown -R flux:flux /app

USER flux

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/health')" || exit 1

# Expose ports: WebSocket, Dashboard, Health
EXPOSE 8765 8080 8766

# Default: run daemon (manages all services)
CMD ["python", "daemon.py"]

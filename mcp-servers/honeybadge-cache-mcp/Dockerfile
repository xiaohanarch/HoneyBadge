FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps -e .
COPY mcp-servers/honeybadge-cache-mcp/ ./mcp-servers/honeybadge-cache-mcp/
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "-m", "honeybadge.__main__", "cache-mcp"]

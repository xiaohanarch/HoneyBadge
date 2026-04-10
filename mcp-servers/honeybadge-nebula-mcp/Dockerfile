FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps -e .
COPY mcp-servers/honeybadge-nebula-mcp/ ./mcp-servers/honeybadge-nebula-mcp/
COPY prompts/ ./prompts/
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('localhost',8000),2); s.close()" || exit 1
CMD ["python", "-m", "honeybadge.__main__", "nebula-mcp"]

FROM python:3.11-slim
WORKDIR /app
COPY mcp-servers/honeybadge-audit-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/honeybadge /app/src/honeybadge
COPY mcp-servers/honeybadge-audit-mcp/server.py /app/server.py
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "server.py"]

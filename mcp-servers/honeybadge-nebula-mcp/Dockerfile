FROM python:3.11-slim
WORKDIR /app
COPY mcp-servers/honeybadge-nebula-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/honeybadge /app/src/honeybadge
COPY prompts /app/prompts
COPY mcp-servers/honeybadge-nebula-mcp/server.py /app/server.py
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "server.py"]

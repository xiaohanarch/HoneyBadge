FROM python:3.11-slim
WORKDIR /app
COPY mcp-servers/honeybadge-cache-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/honeybadge /app/src/honeybadge
COPY mcp-servers/honeybadge-cache-mcp/server.py /app/server.py
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "server.py"]

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn pyyaml
COPY src/honeybadge/__init__.py /app/honeybadge/__init__.py
COPY src/honeybadge/permission_service/ /app/honeybadge/permission_service/
RUN touch /app/honeybadge/__init__.py /app/honeybadge/permission_service/__init__.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import socket; socket.create_connection(('localhost', 8092), timeout=5)" || exit 1
CMD ["uvicorn", "honeybadge.permission_service.main:app", "--host", "0.0.0.0", "--port", "8092"]

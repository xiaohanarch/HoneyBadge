# src/honeybadge/permission_service/Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY src/honeybadge/__init__.py /app/honeybadge/__init__.py
COPY src/honeybadge/permission_service/ /app/honeybadge/permission_service/
RUN touch /app/honeybadge/__init__.py /app/honeybadge/permission_service/__init__.py
CMD ["uvicorn", "honeybadge.permission_service.main:app", "--host", "0.0.0.0", "--port", "8092"]

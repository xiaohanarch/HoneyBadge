FROM python:3.12-slim
WORKDIR /app
# Install only what auth_service needs
RUN pip install --no-cache-dir fastapi uvicorn "python-jose[cryptography]" httpx structlog "passlib[bcrypt]" "bcrypt==4.0.1"
# Copy source files needed
COPY src/honeybadge/server/auth.py /app/honeybadge/server/auth.py
COPY src/honeybadge/server/__init__.py /app/honeybadge/server/__init__.py
COPY src/honeybadge/__init__.py /app/honeybadge/__init__.py
COPY src/honeybadge/auth_service/ /app/honeybadge/auth_service/
# Create __init__.py files
RUN touch /app/honeybadge/__init__.py /app/honeybadge/server/__init__.py /app/honeybadge/auth_service/__init__.py
CMD ["uvicorn", "honeybadge.auth_service.main:app", "--host", "0.0.0.0", "--port", "8091"]

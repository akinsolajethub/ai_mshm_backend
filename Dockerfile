FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make scripts executable
RUN chmod +x scripts/wait_for_services.py

# Create logs directory (required for RotatingFileHandler at build time)
RUN mkdir -p /app/logs

ENV DJANGO_SETTINGS_MODULE=config.settings.production

RUN SECRET_KEY=dummy-build-time-secret-key-not-used-in-production \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Wait for dependencies, collect static, migrate, then start Django with ASGI (WebSocket support)
CMD ["sh", "-c", "python scripts/wait_for_services.py && python manage.py collectstatic --noinput && python manage.py migrate --noinput && daphne -b 0.0.0.0 -p 8000 config.asgi:application"]

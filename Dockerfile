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

EXPOSE 8000

# Wait for dependencies then start Django via Daphne (ASGI)
CMD ["sh", "-c", "python scripts/wait_for_services.py && python manage.py migrate --noinput && daphne -b 0.0.0.0 -p 8000 config.asgi:application"]

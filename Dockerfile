FROM python:3.11-slim

WORKDIR /app

# System dependencies (gcc for web3/cryptography compilation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Collect static files at build time
ENV SECRET_KEY=dummy-build-key-replaced-at-runtime
ENV DJANGO_DEBUG=false
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD daphne -b 0.0.0.0 -p ${PORT:-8000} auction_site.asgi:application

FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY apps/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1

# Copy shared packages
COPY packages /app/packages
ENV PYTHONPATH=/app

# Copy application code
COPY apps/gateway /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

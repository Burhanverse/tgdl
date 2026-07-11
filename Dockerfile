FROM python:3.12-slim

# ffmpeg is optional but gallery-dl / video handling benefits from it being present
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd -m botuser && mkdir -p /app/data /app/logs && chown -R botuser:botuser /app
USER botuser

VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["python", "-m", "app.bot"]

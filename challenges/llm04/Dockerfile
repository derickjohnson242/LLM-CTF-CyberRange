FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5004
# Single worker on purpose: state lives in process memory and must be shared by every request.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:5004", "app:app"]

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN chown -R pwuser:pwuser /app
USER pwuser
# Root filesystem is read-only; Chromium writes its profile to the /tmp tmpfs.
ENV HOME=/tmp

EXPOSE 5010
# Single worker on purpose: state lives in process memory and must be shared by every request.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:5010", "app:app"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HUBMAIL_KEY_FILE=/data/.hubmail_key

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY migrations ./migrations
COPY apply_migrations.py .

EXPOSE 8502

CMD ["sh", "-c", "python apply_migrations.py && uvicorn app.main:app --host 0.0.0.0 --port 8502"]
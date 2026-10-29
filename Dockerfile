FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/joop.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY joop ./joop

RUN useradd --create-home --uid 10001 joop && mkdir -p /data && chown joop /data
USER joop
VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "joop", "serve", "--host", "0.0.0.0", "--port", "8000"]

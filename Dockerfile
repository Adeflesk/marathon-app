FROM python:3.11-slim

# tzdata so TZ (set in fly.toml) gives the right "today" for the plan
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# app/ plus settings.json if you have one (.dockerignore keeps .env, data/ and .venv out)
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

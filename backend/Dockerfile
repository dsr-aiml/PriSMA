FROM node:22-bookworm-slim AS scanners
WORKDIR /scanners
COPY scanners/package.json scanners/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt \
    && python -c "import psycopg; assert psycopg.pq.version() > 0" \
    && useradd -m appuser
COPY . .
COPY --from=scanners /usr/local/bin/node /usr/local/bin/node
COPY --from=scanners /scanners/node_modules /app/scanners/node_modules
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

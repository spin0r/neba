# Build the TypeScript frontend
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app
COPY --from=frontend /build/dist /app/frontend/dist

RUN pip install --no-cache-dir -e ".[bot]"

CMD ["aebndl-bot"]

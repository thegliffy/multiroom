FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY hub/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hub/ ./hub/
COPY --from=web-build /web/dist ./hub/static
ENV PYTHONPATH=/app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn hub.main:app --host ${HUB_HOST:-0.0.0.0} --port ${HUB_PORT:-8080}"]

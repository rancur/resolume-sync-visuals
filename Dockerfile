# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build || mkdir -p dist

# Stage 2: Python backend
FROM python:3.13-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    ffmpeg libsndfile1 openssh-client git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." && \
    pip install --no-cache-dir fastapi uvicorn[standard] python-multipart aiofiles

# App code
COPY src/ src/
COPY server/ server/
COPY config/ config/
COPY assets/ assets/
COPY models/ models/
COPY docs/ docs/

# Frontend build
COPY --from=frontend-build /app/web/dist/ /app/static/

# SSH config for NAS access
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

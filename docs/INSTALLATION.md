# Installation Guide

Resolume Sync Visuals (RSV) generates AI-powered visuals synced to your DJ tracks. This guide covers every installation method.

## Prerequisites

- **fal.ai API key** — for video generation ([get one here](https://fal.ai/dashboard/keys))
- **OpenAI API key** — for prompt generation ([get one here](https://platform.openai.com/api-keys))
- **Lexicon DJ** running on your network (for track metadata)
- **NAS or network storage** accessible via SSH (where your music files live)

Optional:
- **Resolume Arena** with REST API enabled (for live visual control)

---

## Option 1: Docker on Synology NAS

### 1. Install Docker (Container Manager)

Open **Package Center** on your Synology and install **Container Manager** (previously called Docker).

### 2. Create project directory

SSH into your Synology or use File Station to create:

```
/volume1/docker/resolume-sync-visuals/
```

### 3. Create environment file

Create `/volume1/docker/resolume-sync-visuals/.env`:

```env
FAL_KEY=your_fal_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
LEXICON_HOST=your_lexicon_ip
LEXICON_PORT=48624
NAS_HOST=your_nas_ip
NAS_SSH_PORT=7844
NAS_USER=your_nas_username
NAS_SSH_KEY=/root/.ssh/id_ed25519
RESOLUME_HOST=127.0.0.1
RESOLUME_PORT=8080
```

### 4. Create docker-compose.yml

Create `/volume1/docker/resolume-sync-visuals/docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/rancur/resolume-sync-visuals:latest
    ports:
      - "8765:8000"
    volumes:
      - rsv-data:/root/.rsv
      - /volume1/homes/your_user/.ssh/id_ed25519:/root/.ssh/id_ed25519:ro
    env_file: .env
    restart: unless-stopped

volumes:
  rsv-data:
```

### 5. Start the container

In Container Manager, go to **Project** > **Create** > select the folder, or via SSH:

```bash
cd /volume1/docker/resolume-sync-visuals
docker compose up -d
```

### 6. Open the web UI

Navigate to `http://your-synology-ip:8765`. The first-run setup wizard will guide you through configuration.

---

## Option 2: Docker on Linux

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

### 2. Clone the repository

```bash
git clone https://github.com/rancur/resolume-sync-visuals.git
cd resolume-sync-visuals
```

### 3. Create environment file

```bash
cp .env.example .env
# Edit .env with your API keys and connection settings
```

If `.env.example` doesn't exist, create `.env` with the variables listed in the [Environment Variables Reference](#environment-variables-reference) below.

### 4. Start

```bash
docker compose up -d
```

### 5. Open the web UI

Navigate to `http://localhost:8765`. The setup wizard will walk you through remaining configuration.

### Enable auto-updates (optional)

```bash
docker compose --profile auto-update up -d
```

This starts a Watchtower sidecar that checks for new images every hour.

---

## Option 3: Docker on Mac

### 1. Install Docker Desktop

Download and install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/).

### 2. Clone and start

```bash
git clone https://github.com/rancur/resolume-sync-visuals.git
cd resolume-sync-visuals
cp .env.example .env   # then edit with your keys
docker compose up -d
```

### 3. Open the web UI

Navigate to `http://localhost:8765`.

**Note for Apple Silicon (M1/M2/M3/M4):** The Docker image is built for `linux/amd64` and `linux/arm64`. If you experience issues, build locally:

```bash
docker compose build
docker compose up -d
```

---

## Option 4: Direct Python Install (No Docker)

### 1. Requirements

- Python 3.9+
- FFmpeg
- Node.js 18+ (for building the web UI)
- SSH client (for NAS access)

### 2. Install system dependencies

**macOS:**
```bash
brew install ffmpeg node python@3.13
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-pip python3-venv nodejs npm libsndfile1
```

### 3. Clone the repository

```bash
git clone https://github.com/rancur/resolume-sync-visuals.git
cd resolume-sync-visuals
```

### 4. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "."
pip install fastapi uvicorn[standard] python-multipart aiofiles
```

### 5. Build the web UI

```bash
cd web
npm ci
npm run build
cd ..
```

### 6. Set environment variables

```bash
export FAL_KEY="your_fal_api_key"
export OPENAI_API_KEY="your_openai_api_key"
export LEXICON_HOST="your_lexicon_ip"
export LEXICON_PORT="48624"
export NAS_HOST="your_nas_ip"
export NAS_SSH_PORT="7844"
export NAS_USER="your_user"
export NAS_SSH_KEY="$HOME/.ssh/id_ed25519"
```

Or create a `.env` file and source it: `source .env`

### 7. Start the server

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### 8. Open the web UI

Navigate to `http://localhost:8000`.

---

## First-Run Configuration

On first launch, RSV detects missing configuration and presents a setup wizard that walks through:

1. **API Keys** — Enter your fal.ai and OpenAI keys
2. **NAS Connection** — Host, SSH port, username, SSH key path (with "Test Connection" button)
3. **Lexicon DJ** — Host and port (with "Test Connection" button)
4. **Resolume Arena** — Host and port (optional, with "Test Connection" button)

You can re-configure everything later from the **Settings** page.

### Setup Status API

Check configuration status programmatically:

```
GET /api/setup/status
```

Returns:
```json
{
  "setup_complete": false,
  "sections": {
    "api_keys": { "complete": false, "fields": { ... } },
    "nas": { "complete": true, "fields": { ... } },
    "lexicon": { "complete": true, "fields": { ... } },
    "resolume": { "complete": true, "fields": { ... } }
  }
}
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FAL_KEY` | Yes | — | fal.ai API key for video generation |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for prompt generation |
| `LEXICON_HOST` | Yes | `127.0.0.1` | Lexicon DJ server IP/hostname |
| `LEXICON_PORT` | Yes | `48624` | Lexicon DJ API port |
| `NAS_HOST` | Yes | `localhost` | NAS IP/hostname for SSH access |
| `NAS_SSH_PORT` | No | `7844` | NAS SSH port |
| `NAS_USER` | Yes | `admin` | NAS SSH username |
| `NAS_SSH_KEY` | No | `~/.ssh/id_ed25519` | Path to SSH private key for NAS |
| `RESOLUME_HOST` | No | `127.0.0.1` | Resolume Arena REST API host |
| `RESOLUME_PORT` | No | `8080` | Resolume Arena REST API port |
| `RSV_DB_PATH` | No | `~/.rsv` | Path for SQLite database and data |
| `LOG_RETENTION_DAYS` | No | `365` | Days to keep log entries |

---

## Updating

### Docker

Check for updates from the Settings page (Settings > Version & Updates > Check for Updates), or manually:

```bash
docker compose pull
docker compose up -d
```

### Direct Python install

```bash
git pull
pip install -e "."
cd web && npm ci && npm run build && cd ..
# Restart the server
```

---

## Troubleshooting

### NAS connection fails
- Verify SSH key permissions: `chmod 600 ~/.ssh/id_ed25519`
- Test manually: `ssh -p 7844 -i ~/.ssh/id_ed25519 user@nas-host`
- In Docker, ensure the key is mounted as a volume

### Lexicon connection fails
- Ensure Lexicon DJ is running and its API is enabled
- Check the host/port — Lexicon default API port is 48624
- Verify no firewall is blocking the connection

### Web UI shows blank page
- Check if the frontend was built: `ls web/dist/index.html`
- In Docker: `docker compose logs app`
- Direct install: check terminal output for errors

### Port conflicts
- Change the host port in docker-compose.yml: `"9000:8000"` instead of `"8765:8000"`
- Direct install: `uvicorn server.main:app --port 9000`

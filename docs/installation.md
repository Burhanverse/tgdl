# System Requirements & Installation Guide

This guide covers system prerequisites, manual local installation, environment variables, and Docker deployment.

---

## System Prerequisites

Before running TGDL Bot, ensure the following system dependencies are installed on your host OS:

- **Python**: 3.12 or newer
- **FFmpeg & FFprobe**: Required for video metadata extraction, thumbnail generation, and audio/video transcoding.
- **aria2c**: Required for direct multi-connection HTTP downloads and torrent/magnet link handling.
- **System Archive Utilities** (for `patool` archive support):
  - Linux: `unzip`, `unrar` / `rar`, `p7zip-full` / `7z`, `tar`, `gzip`, `bzip2`, `xz-utils`

### Installing Prerequisites on Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg aria2 unzip p7zip-full tar gzip bzip2 xz-utils
```

---

## Local Installation

1. **Clone Repository**:
   ```bash
   git clone https://github.com/Burhanverse/tgdl.git
   cd tgdl
   ```

2. **Create & Activate Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```
   Required variables:
   - `TG_API_ID`: Telegram API ID obtained from [my.telegram.org](https://my.telegram.org).
   - `TG_API_HASH`: Telegram API Hash.
   - `TG_BOT_TOKEN`: Bot token from [@BotFather](https://t.me/BotFather).

5. **Start Bot**:
   ```bash
   python -m app.bot
   ```

---

## Docker Deployment

Deploy using Docker Compose for containerized execution.

1. Configure `.env` file as shown above.
2. Build and start containers:
   ```bash
   docker compose up -d --build
   ```
3. View logs:
   ```bash
   docker compose logs -f
   ```

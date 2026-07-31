# tgdl-bot

An all-in-one Telegram media & file downloader, archive extractor, cloud storage mirror, and torrent manager. Powered by `gallery-dl`, `aria2c`, `Google Drive API`, and Pyrogram to support up to 2GB uploads per file with real-time status management.

---

## Documentation Index

This project uses modular sub-documentation files located in the `docs/` directory:

- **[Direct & Gallery Downloader Reference](docs/downloaders.md)**
  - Direct HTTP/HTTPS downloads (`/dl`, `/direct`).
  - Gallery-dl media extraction from 100+ sites (`/gdl`, `/gallerydl`).
  - Server mirroring (`/m`, `/mirror`).
  - Command flags (`-m`, `-tg`, `-uz`, `-p <password>`) and batch `.txt` link file processing.

- **[Torrent Downloads & Search Engine](docs/torrents.md)**
  - Headless torrent and magnet downloading (`/tor`).
  - Interactive multi-provider Torrent Search Engine (`/ts`, `/torsearch`, `/search`).

- **[Archive Extraction & Volume Splitting](docs/archives.md)**
  - Single archive decompression (`/unzip [password]`).
  - Split archive collector sessions (`/unzip split`).
  - Multi-archive batch extractions (`/unzip multi`).
  - Interactive password prompts and Telegram 2GB upload limit safeguards.

- **[Cloud Storage & Google Drive Integration](docs/cloud_and_drive.md)**
  - Google Drive folder and file downloader (`/gd2tg`).
  - Google Drive authentication guide (Service Accounts & OAuth tokens).
  - External cloud host uploaders: Pixeldrain (`/pdup`), GoFile (`/gfup`), FileDitch (`/fdup`).

- **[Custom Configuration, Cookies & Task Controls](docs/configuration.md)**
  - Per-user `gallery-dl.conf` and `cookies.txt` manager (`/gdlconf`).
  - Live task monitor, queue dashboard, and speed metrics (`/status`).
  - Job cancellation (`/cancel [job_id]`).

- **[Installation & System Requirements](docs/installation.md)**
  - System prerequisites (FFmpeg, aria2, archive utilities).
  - Local virtual environment setup and configuration.
  - Docker deployment using `docker-compose`.

---

## Quick Reference Overview

### Core Commands

| Command | Aliases | Description | Sub-Documentation |
| :--- | :--- | :--- | :--- |
| `/dl [flags] <url>` | `/direct` | Download direct HTTP/HTTPS URLs. | [Downloaders](docs/downloaders.md) |
| `/gdl [flags] <url>` | `/gallerydl` | Download albums/posts via gallery-dl. | [Downloaders](docs/downloaders.md) |
| `/mega [flags] <url>` | `/meganz` | Download files & folders from mega.nz / mega.co.nz / mega.io. | [Downloaders](docs/downloaders.md) |
| `/mega -login <email:pass>` | `/mega -logout`, `/mega -account` | Manage personal MEGA account credentials. | [Cloud & Drive](docs/cloud_and_drive.md) |
| `/m [flags] <url>` | `/mirror` | Mirror links/files to server. | [Downloaders](docs/downloaders.md) |
| `/tor <magnet/url>` | — | Download torrent magnet or `.torrent` file. | [Torrents](docs/torrents.md) |
| `/ts <query>` | `/torsearch`, `/search` | Search torrents with inline pagination. | [Torrents](docs/torrents.md) |
| `/unzip [password]` | — | Extract archive files. | [Archives](docs/archives.md) |
| `/unzip split` | — | Multi-part split archive collector session. | [Archives](docs/archives.md) |
| `/unzip multi` | — | Multi-archive batch extraction session. | [Archives](docs/archives.md) |
| `/gd2tg <gdrive_link>` | — | Download Google Drive link to Telegram. | [Cloud & Drive](docs/cloud_and_drive.md) |
| `/pdup` | — | Upload replied media to Pixeldrain. | [Cloud & Drive](docs/cloud_and_drive.md) |
| `/gfup` | `/gofile` | Upload replied media to GoFile. | [Cloud & Drive](docs/cloud_and_drive.md) |
| `/fdup` | `/fileditch` | Upload replied media to FileDitch. | [Cloud & Drive](docs/cloud_and_drive.md) |
| `/gdlconf` | `/gdl_config` | Manage custom gallery-dl config & cookies. | [Configuration](docs/configuration.md) |
| `/status` | — | Interactive real-time task manager. | [Configuration](docs/configuration.md) |
| `/cancel [job_id]` | — | Cancel active/queued job. | [Configuration](docs/configuration.md) |
| `/help` | `/start` | Open interactive paged help menu. | — |

---

## Quick Start Example

```bash
# 1. Clone repository
git clone https://github.com/Burhanverse/tgdl.git
cd tgdl

# 2. Synchronize dependencies using uv
uv sync

# 3. Configure credentials in .env and launch
cp .env.example .env
uv run python -m app.bot
```

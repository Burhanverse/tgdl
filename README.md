# tgdl-bot

A minimal Telegram bot that downloads media albums, videos, and torrents via `gallery-dl` and `aria2c` and uploads them to Telegram. Built on Kurigram (pyrogram fork) to support up to 2GB uploads.

---

## Features
- **Concurrent Pipeline**: Downloads and uploads run in parallel to minimize latency.
- **Space Protection**: Completed uploads are deleted immediately to conserve disk space.
- **Auto-Splitting**: Prompts to split files larger than 1.95GB into sub-2GB segments or skip them.
- **Live Status & Speed**: Real-time progress updates with monospace progress bars and throttled edit protection.
- **Multi-URL Downloads**: Process a list of space-separated links or a `.txt` links file reply sequentially.
- **Timeline Screenshots**: Generates and uploads timeline screenshots grouped in a separate album after the main video.
- **Torrent/Magnet Support**: Download torrents or magnet links headless using `aria2c` with custom speed parsing.
- **Lossless Media Transcoding**: Interactive video container conversions to MP4 (using FFmpeg stream copy) and image transcoding of WebP, BMP, HEIC, etc., to PNG for inline photo display.
- **Interactive Decompression**: Pauses and prompts the user to select extraction choices when zip/rar/7z archives are downloaded.

---

## Usage

### Commands
- `/start` — Display welcome message and instructions.
- `/gdl` — Process replied `.txt` links files.
- `/tor` — Download magnet/torrent links or reply to a `.torrent` file.
- `/unzip` — Reply to a compressed archive file to extract and upload its contents.
- `/status` — View active job status or queue state.
- `/cancel` — Instantly abort the active job or cancel queued jobs.

### Input Formats
- **Single URL**: `https://example.com/album1`
- **With Shorthands**: `https://example.com/album1 pages=1-16`
- **Multiple URLs**: `https://example.com/album1 https://example.com/album2`
- **Links File (.txt)**: Reply to a `.txt` file containing URLs (one per line) with `/gdl`.
- **Torrents**: `/tor magnet:?xt=urn:...` or reply to a `.torrent` file with `/tor`.
- **Archive Extract**: Reply to any `.zip`, `.rar`, `.7z`, etc., file with `/unzip`.

---

## Setup & Running

### Prerequisites
- Python 3.12+
- `ffmpeg` & `ffprobe` (for video transcoding, screenshots, and metadata probing)
- `aria2c` (for torrent and magnet link downloads)
- `unzip`, `unrar`, `7z` (for archive extraction)

### Getting Started
1. Copy `.env.example` to `.env` and fill in `TG_API_ID`, `TG_API_HASH`, and `TG_BOT_TOKEN`.
2. Install dependencies and run:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m app.bot
   ```

### Docker
```bash
docker compose up -d --build
```

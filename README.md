# tgdl-bot

Telegram bot that downloads links via `gallery-dl` and uploads the results
back into the chat, using Kurigram (MTProto) for a 2GB upload ceiling
instead of the 50MB HTTP Bot API limit.

## Features

- **Persistent job queue** (SQLite) — survives restarts. A 1600-file album
  interrupted at file 800 resumes from 800, not 0.
- **Two layers of resumability**: gallery-dl's own `--download-archive`
  skips already-fetched source files; a separate `uploaded_files` table
  skips already-uploaded files, independently.
- **Adaptive backoff** on gallery-dl runs — if output looks like a
  rate-limit/block response (429/403/"too many requests"), the bot backs
  off exponentially and retries instead of failing outright.
- **Paced uploads** with jittered delays, batch cooldowns, and automatic
  `FloodWait` handling.
- **Live progress** during both download and upload phases, throttled so
  status edits themselves don't trip rate limits.
- **/status** and **/cancel** commands.
- **Graceful shutdown** — SIGTERM/SIGINT finishes the current file, marks
  the job for resume, and exits cleanly (important for `systemctl restart`
  or container redeploys mid-job).

## Setup

```bash
cp .env.example .env
# edit .env: TG_API_ID / TG_API_HASH from https://my.telegram.org,
# TG_BOT_TOKEN from @BotFather

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run directly:

```bash
python -m app.bot
```

## Deployment

### Docker

```bash
docker compose up -d --build
docker compose logs -f
```

### systemd (bare metal / VPS)

```bash
sudo useradd -r -m -d /opt/tgdl-bot tgdlbot
sudo cp -r . /opt/tgdl-bot
cd /opt/tgdl-bot
sudo -u tgdlbot python3 -m venv .venv
sudo -u tgdlbot .venv/bin/pip install -r requirements.txt
sudo cp tgdl-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tgdl-bot
sudo journalctl -u tgdl-bot -f
```

## Tuning

Everything is in `.env` / `app/config.py`:

- `GDL_SLEEP_MIN/MAX`, `GDL_LIMIT_RATE` — how gently gallery-dl treats the
  source site. Loosen once you've confirmed the site tolerates it.
- `GDL_MAX_RUN_RETRIES`, `GDL_BACKOFF_BASE_S` — how the bot reacts to
  rate-limit signals from the source.
- `TG_UPLOAD_DELAY_MIN/MAX`, `TG_BATCH_SIZE`, `TG_BATCH_COOLDOWN_S` —
  Telegram-side upload pacing.
- `TG_MAX_CONCURRENT_UPLOADS` — leave at 1 unless you've tested that your
  bot account tolerates parallel uploads without harsher flood limits.

## Notes

- Only fetch/redistribute content you actually have the rights to.
- Kurigram and the original `pyrogram` package share the same import
  namespace — don't install both in one environment.
- The 2GB cap is the MTProto ceiling for bot accounts; nothing in this app
  can raise that further.

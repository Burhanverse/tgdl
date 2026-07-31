# Custom Configuration, Cookies & Task Controls

This guide explains per-user `gallery-dl.conf` and `cookies.txt` management, live task monitoring, and job cancellation.

---

## Gallery-dl Config & Cookies Manager (`/gdlconf`)

Configure custom authentication, headers, or settings for `gallery-dl`.

### Syntax
```text
/gdlconf
/gdl_config
```

### Uploading Cookies
1. Export cookies from your browser (e.g. using *Get cookies.txt* extension).
2. Upload `cookies.txt` to the Telegram bot chat.
3. Reply to the `cookies.txt` file with `/gdlconf`.

### Security & Postprocessor Sanitization
All uploaded `gallery-dl.conf` files are automatically scanned and validated. Any dangerous postprocessors (e.g. `exec`, `python`, `cmd`, `shell`) are denied by default to ensure host security.

---

## Live Task & Queue Dashboard (`/status`)

Monitor download/upload speeds, active tasks, queued items, and overall performance.

### Syntax
```text
/status
/status me
```

### Features
- **Live Progress Bars**: Real-time progress percentage, ETA, and transfer speed.
- **Pagination Controls**: `Prev` and `Next` buttons for managing large task queues.
- **Task Overview Mode**: Click `Overview` button to see job state counts (Downloads, Uploads, Archives, Conversions) and overall speed totals.
- **Inline Job Cancel Buttons**: Cancel any individual active task directly from the status display.

---

## Job Cancellation (`/cancel`)

Cancel active or queued jobs instantly.

### Syntax
```text
/cancel [job_id]
```

### Usage
- Cancel specific job ID:
  ```text
  /cancel abc12345
  ```
- Send `/cancel` without arguments to open an interactive selection menu of all your active/queued jobs.

---

## Authorization & Security Controls (`.env`)

Configure access control and security policies in `.env`:
- `AUTHORIZED_USER_IDS`: Comma-separated list of allowed Telegram user IDs (e.g. `12345678,98765432`).
- `AUTHORIZED_CHAT_IDS`: Comma-separated list of allowed Telegram group/channel IDs (e.g. `-100123456789`).
- `MAX_JOBS_PER_CHAT`: Maximum concurrent active + queued jobs allowed per chat (default `3`).
- `MAX_TOTAL_DOWNLOADS_BYTES`: Optional cap on total `downloads_dir` storage usage.
- `ALLOW_SHARED_UPLOAD_KEYS`: Fall back to owner's global API keys for uploaders (default `false`).
- `ALLOW_PRIVATE_NETWORK_URLS`: Allow downloading URLs resolving to private/reserved IP ranges (default `false` for SSRF protection).


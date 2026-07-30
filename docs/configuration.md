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

### Uploading Custom Configuration
1. Create a custom JSON `.conf` file for gallery-dl.
2. Upload the file to the bot chat and reply to it with `/gdlconf`.

### Interactive Management Menu
Send `/gdlconf` to open the control panel:
- **View Active Config**: Inspect current user-level configuration JSON.
- **View Default Config**: View global template configuration.
- **Download Config File**: Receive your active `.conf` file as a document.
- **Delete Cookies**: Remove stored `cookies.txt`.
- **Reset Configuration**: Restore default settings.

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

## Global Environment Credentials

You can set global fallback credentials in your `.env` file:
- `MEGA_EMAIL`: Default global MEGA account email.
- `MEGA_PASSWORD`: Default global MEGA account password.
- `PIXELDRAIN_API_KEY`: API key for Pixeldrain uploads (`/pdup`).
- `GOFILE_API_KEY`: API token for GoFile uploads (`/gfup`).


# Cloud Storage & Google Drive Integration

This guide covers Google Drive downloading (`/gd2tg`), Service Account setup, and direct cloud host uploaders (Pixeldrain, GoFile, FileDitch).

---

## Google Drive Downloader (`/gd2tg`)

Download files or full folder structures from Google Drive directly to Telegram.

### Syntax
```text
/gd2tg <gdrive_url>
```

### Examples
```text
/gd2tg https://drive.google.com/drive/folders/1abc123xyz...
/gd2tg https://drive.google.com/file/d/1abc123xyz.../view
```

---

## Google Drive Authentication Setup

To use `/gd2tg`, credential files must be placed under `auth/<user_id>/` (per-user isolation) or `auth/` (global fallback).

### Method 1: Service Accounts (Recommended)
Service Accounts bypass Google Drive's 750 GB/day per-account download quota and require zero browser steps:
1. Create a Service Account in Google Cloud Console (**IAM & Admin > Service Accounts**).
2. Create and download a **JSON** key.
3. Upload the `.json` key to the Telegram bot chat and **reply to it with `/gd2tg`**. The bot saves it to `auth/<user_id>/accounts/`.

### Method 2: OAuth User Token
1. Generate a `token.pickle` file using Google API OAuth credentials.
2. Upload `token.pickle` to the Telegram bot chat and **reply to it with `/gd2tg`**. The bot saves it to `auth/<user_id>/token.pickle`.

### Method 3: Global Credentials (Bot Owner Setup)
If the bot owner places `token.pickle` or `accounts/*.json` files in the server `auth/` folder, all users can use `/gd2tg` immediately without uploading credentials.

---

## External Cloud Host Uploaders

Upload Telegram media files directly to third-party file hosting services.

### Commands

| Host | Command | Aliases | Usage |
| :--- | :--- | :--- | :--- |
| **Pixeldrain** | `/pdup` | — | Reply to any Telegram file or video message with `/pdup`. |
| **GoFile** | `/gfup` | `/gofile` | Reply to any Telegram file or video message with `/gfup` or `/gofile`. |
| **FileDitch** | `/fdup` | `/fileditch` | Reply to any Telegram file or video message with `/fdup` or `/fileditch`. |

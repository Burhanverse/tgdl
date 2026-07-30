# Direct & Gallery Downloader Reference

This guide covers direct HTTP/HTTPS file downloading, gallery-dl media extraction, server mirroring, and supported command flags.

---

## Direct Downloader (`/dl`, `/direct`)

The `/dl` (or `/direct`) command uses `aria2c` multi-connection downloading or direct HTTP streams to pull files at maximum speed.

### Syntax
```text
/dl [flags] <url>
/direct [flags] <url>
```

### Examples
- Download a single direct file:
  ```text
  /dl https://example.com/file.zip
  ```
- Download direct file and extract automatically:
  ```text
  /dl -uz -p secret123 https://example.com/archive.zip
  ```

---

## Gallery Downloader (`/gdl`, `/gallerydl`)

The `/gdl` (or `/gallerydl`) command uses `gallery-dl` to extract media albums, images, artwork, posts, and videos from over 100 supported sites.

### Syntax
```text
/gdl [flags] <url>
/gallerydl [flags] <url>
```

### Examples
- Download a social media post or gallery to Telegram:
  ```text
  /gdl -tg https://twitter.com/user/status/123456789
  ```
- Download media album with mirror mode enabled:
  ```text
  /gdl -m https://pixiv.net/artworks/123456
  ```

---

## MEGA Downloader (`/mega`, `/meganz`)

The `/mega` (or `/meganz`) command downloads files and full folder hierarchies from **mega.nz**, **mega.co.nz**, and **mega.io**.

### Syntax
```text
/mega [flags] <mega_url>
/meganz [flags] <mega_url>
```

### Examples
- Download a public file or folder:
  ```text
  /mega https://mega.nz/file/ABC#123
  /mega https://mega.nz/folder/XYZ#456
  ```
- Download and automatically extract archives inside MEGA folder:
  ```text
  /mega -uz -p secret123 https://mega.nz/folder/XYZ#456
  ```
- Mirror MEGA contents to server storage:
  ```text
  /mega -m https://mega.nz/file/ABC#123
  ```

---

## Mirror Mode (`/m`, `/mirror`)

The `/m` (or `/mirror`) command downloads content and stores it on server storage.

### Syntax
```text
/m [-tg] <url>
/mirror [-tg] <url>
```
- Replying to a Telegram message with `/m` mirrors the Telegram file to server storage.
- Using `-tg` flag forces re-upload back to Telegram.

---

## Supported Command Flags

The following flags can be passed to `/dl`, `/gdl`, `/mega`, `/direct`, `/gallerydl`, `/meganz`, and `/mirror`:

| Flag | Aliases | Description |
| :--- | :--- | :--- |
| `-m` | `-mirror`, `--mirror` | Enable server mirror mode instead of default upload behavior. |
| `-tg` | `--tg` | Force upload output back to Telegram. |
| `-uz` | `-unzip`, `--unzip` | Automatically extract downloaded archive files upon completion. |
| `-p <pass>` | `-pass`, `--pass`, `--password` | Specify decryption password for protected archives. |

---

## Batch Link Processing

You can process multiple URLs in a single job:
1. Paste space-separated URLs in the command:
   ```text
   /gdl https://example.com/album1 https://example.com/album2
   /mega https://mega.nz/file/ABC#123 https://mega.nz/file/DEF#456
   ```
2. Reply to a `.txt` file containing URLs (one per line) with `/dl`, `/gdl`, or `/mega`.


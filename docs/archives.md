# Archive Extraction & Volume Splitting Reference

This guide explains single archive extraction, split archive collection sessions, multi-archive batch processing, and password handling.

---

## Single Archive Extraction (`/unzip`)

Extract `.zip`, `.rar`, `.7z`, `.tar`, `.gz`, `.bz2`, `.xz` archives.

### Syntax
```text
/unzip [password]
```
Reply to an archive document in Telegram with `/unzip` (or `/unzip secretpass` if password-protected).

---

## Split Archive Collector (`/unzip split`)

Combine and extract multi-part split archives (e.g. `.001`, `.002`, `.part1.rar`, `.part2.rar`).

### Workflow
1. Send `/unzip split [password]` in chat.
2. Upload or forward all split archive parts to the chat.
3. The bot automatically groups parts and displays a live session status message.
4. Click **Start Extraction** when all parts are uploaded.

---

## Multi-Archive Batch Processing (`/unzip multi`)

Batch extract multiple archives uploaded sequentially.

### Workflow
1. Send `/unzip multi [password]` in chat.
2. Upload multiple archive files into the chat.
3. Click **Start Batch Extraction** to unpack all uploaded archives.

---

## Password Protection & Large File Safeguards

- **Interactive Password Prompt**: If an archive requires a password and none was specified, the bot pauses and prompts you interactively for the password.
- **Telegram 2GB Limit Safeguard**: If extracted files exceed Telegram's 2GB upload limit, the bot prompts whether to split files into sub-2GB volumes or skip oversized files.

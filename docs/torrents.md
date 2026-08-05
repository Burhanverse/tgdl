# Torrent & Magnet Link Downloader & Search Engine

This guide covers torrent and magnet downloading via `aria2c` and the interactive Torrent Search Engine.

---

## Torrent Downloader (`/tor`)

Download torrent files or magnet links headlessly with real-time peer count, seeders, and speed metrics.

### Syntax
```text
/tor <magnet_link_or_url>
```
Or reply to a `.torrent` file attachment in chat with `/tor`.

### Examples
- Download a magnet link:
  ```text
  /tor magnet:?xt=urn:btih:123456789abcdef...
  ```
- Download a `.torrent` URL:
  ```text
  /tor https://example.com/file.torrent
  ```
- Uploading `.torrent` file:
  Send a `.torrent` file to the chat and reply to it with `/tor`.

---

## Torrent Search Engine (`/ts`, `/torsearch`, `/search`)

Search for torrents across multiple providers directly within Telegram.

### Syntax
```text
/ts <search_query>
/torsearch <search_query>
/search <search_query>
```

### Examples
```text
/ts Ubuntu 24.04
/search Blender 4.2
```

### Key Search Engine Features
- **Magnetio JSON-RPC Architecture**: Searches across 22 independent torrent providers (ThePirateBay, 1337x, YTS, Kickass, Nyaa, LimeTorrents, Bitsearch, BT4G, BTdig, etc.) via an isolated Node.js Express JSON-RPC 2.0 sidecar (`magnetio-scraper`).
- **Inline Pagination & Telegraph Rendering**: View formatted HTML results directly in Telegram or full telegraph pages for large query results.
- **1-Click Magnet Share**: Each search result includes pre-constructed magnet links for instant sharing and downloading via `/tor`.

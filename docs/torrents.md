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
- **Multi-Provider Querying**: Searches across 1337x, YTS, PirateBay, TorrentProject, and other public indexers.
- **Inline Pagination**: Navigate through search result pages using interactive `Prev` and `Next` buttons.
- **1-Click Download**: Each search result includes a direct **Download with /tor** inline button to enqueue the torrent instantly.

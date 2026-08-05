# Magnetio Scraper JSON-RPC 2.0 API Specification

The Magnetio scraper sidecar exposes a JSON-RPC 2.0 endpoint at `POST /rpc`.

## Authentication

If `RPC_SHARED_SECRET` environment variable is set on the scraper service, all JSON-RPC calls must include authorization:
- HTTP Header: `Authorization: Bearer <RPC_SHARED_SECRET>`
- OR request param: `"secret": "<RPC_SHARED_SECRET>"`

If authorization fails or is missing, the response will be a JSON-RPC error with code `-32001` ("Unauthorized").

---

## Methods

### `torrent.search`

Scrapes enabled torrent providers for free-text or structured media queries.

#### Parameters

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | **Yes** | Search terms |
| `type` | `string` | No | `"movie"` (default), `"series"`, or `"anime"` |
| `year` | `number` | No | Release year |
| `season` | `number` | No | Season number (for series) |
| `episode` | `number` | No | Episode number (for series) |
| `providers` | `string[]` | No | List of provider IDs to scrape (e.g. `["thepiratebay", "yts"]`). Scrapes all providers if omitted |
| `limit` | `number` | No | Maximum number of results to return |
| `strict` | `boolean` | No | Default `true`. If `false`, disables title phrase content matching for looser free-text queries |

#### Example Request

```json
{
  "jsonrpc": "2.0",
  "method": "torrent.search",
  "params": {
    "query": "Ubuntu 22.04",
    "limit": 10,
    "strict": false
  },
  "id": 1
}
```

#### Example Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "count": 1,
    "torrents": [
      {
        "title": "ubuntu-22.04.3-desktop-amd64.iso",
        "infoHash": "45a305e26090e543666b6cfa45d6541f486431bd",
        "seeders": 150,
        "leechers": 10,
        "size": 4970422272,
        "provider": "ThePirateBay",
        "quality": null,
        "codec": null,
        "source": null,
        "languages": [],
        "magnet": "magnet:?xt=urn:btih:45a305e26090e543666b6cfa45d6541f486431bd&dn=ubuntu-22.04.3-desktop-amd64.iso&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
      }
    ]
  }
}
```

---

### `torrent.providers`

Lists all available provider scrapers.

#### Example Request

```json
{
  "jsonrpc": "2.0",
  "method": "torrent.providers",
  "id": 2
}
```

#### Example Response

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "providers": [
      { "id": "thepiratebay", "name": "ThePirateBay" },
      { "id": "yts", "name": "YTS" },
      { "id": "nyaa", "name": "Nyaa" }
    ]
  }
}
```

---

### `torrent.health`

Returns liveness and service status information.

#### Example Request

```json
{
  "jsonrpc": "2.0",
  "method": "torrent.health",
  "id": 3
}
```

#### Example Response

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "status": "ok",
    "service": "magnetio-scraper",
    "version": "1.1.5"
  }
}
```

---

## Batch Requests

Standard JSON-RPC 2.0 batch array requests are fully supported:

```json
[
  { "jsonrpc": "2.0", "method": "torrent.health", "id": 1 },
  { "jsonrpc": "2.0", "method": "torrent.providers", "id": 2 }
]
```

# Implementation Brief: Magnetio Scraper as a JSON-RPC Torrent Indexer for tgdl

## Context (read first)

Two existing codebases are involved:

1. **tgdl** — a Telegram download bot (Pyrogram). It already runs a self-managed
   `aria2c` daemon in `app/downloader/aria2c/torrent/core.py` and talks to it over
   JSON-RPC 2.0 (`aria2.addUri`, `aria2.tellStatus`, etc. via `sync_rpc_call` /
   `async_rpc_call`). That download path is working and **must not be touched**.
   The weak part is search: `app/downloader/aria2c/torrent/search.py` +
   `app/downloader/aria2c/torrent/indexers/` currently only has 4 basic scrapers
   (apibay, torrents_csv, nyaa, yts) as a last-resort fallback behind optional
   Prowlarr / `SEARCH_API_LINK` integrations. The public search results are
   consumed by `app/handlers/torrent_search.py` (`/torsearch`, `/ts`) and rendered
   via `app/telegraph/telegraph_helper.py`.

2. **Magnetio** — a Stremio addon https://github.com/peterdsp/Magnetio . Its `scraper/` folder is a **standalone Node.js
   (Express) service** with 22 independent provider scrapers (ThePirateBay,
   1337x/leetx, TorrentGalaxy, RARBG mirror, KickassTorrents, EZTV, nyaa,
   AnimeSaturn, Rutor, Rutracker, LimeTorrents, Bitsearch, BT4G, BTdig,
   GloTorrents, Torlock, TorrentDownloads, SubsPlease, AnimeTosho, NekoBT,
   Torznab, YTS — see `scraper/providers/index.js`). It has **no debrid
   dependencies at all** (confirmed in `scraper/package.json`). Its only REST
   endpoint (`GET /streams/:type/:id` in `scraper/index.js`) resolves an IMDb id
   via Cinemeta first, then calls `scrapeAll(type, meta, providerIds, context)`.
   Critically, every provider's `scrape(meta)` function (see
   `scraper/providers/thepiratebay.js`, `scraper/lib/titleHelper.js`) only
   strictly requires `meta.name` — a plain query string — plus optional
   `year`/`season`/`episode`/`type`. Cinemeta resolution is not a hard
   requirement of the scraping layer itself, only of the existing REST route.

Do **not** use anything from Magnetio's `addon/` or `site/` folders, and do not
add any debrid provider. Only `scraper/` is in scope.

## Goal

Stand up Magnetio's `scraper/` as an independent sidecar service exposing a
**JSON-RPC 2.0** interface for free-text torrent search (not just IMDb-id
lookups), and make it the **sole** indexer behind tgdl's existing
`search_torrents()` function — on par with how tgdl already talks JSON-RPC to
its own aria2c daemon. This is a **full replacement**, not an additional tier:
tgdl's existing Prowlarr integration, `SEARCH_API_LINK` integration, and the
old 4-scraper local fallback (`apibay`, `torrents_csv`, `nyaa`, `yts`) are all
being removed. After this change, `search_torrents()` should have exactly one
code path: call the Magnetio RPC sidecar.

## Part A — Add a JSON-RPC 2.0 surface to Magnetio's scraper

Work only inside `scraper/`.

1. Add a new route, `POST /rpc`, implementing JSON-RPC 2.0 request/response
   framing (`jsonrpc: "2.0"`, `id`, `method`, `params`, and proper
   `{code, message}` error objects per the spec) using an existing lightweight
   library if one is already a transitive dependency, otherwise hand-rolled —
   keep it dependency-light. Support **batch requests** (an array of request
   objects) since that's part of the 2.0 spec and something a bot client may
   want later.

2. Implement these RPC methods:
   - `torrent.search` — params: `{ query: string, type?: "movie"|"series"|"anime", year?: number, season?: number, episode?: number, providers?: string[], limit?: number }`.
     - If `season`/`episode` are omitted, treat as a general/movie-style query.
     - Build a synthetic `meta` object (`{ name: query, year, season, episode, type: type ?? "movie" }`)
       and call the existing `scrapeAll(type, meta, providerIds, context)` —
       **do not** call Cinemeta for this path; that's for the IMDb-id-driven REST
       route only, which should be left as-is for backward compatibility.
     - `scrapeAll` currently calls `filterByContent()` which enforces phrase
       matching against `meta.name`. Keep this (it filters junk results) but
       add a `strict?: boolean` param (default `true`) that callers can set to
       `false` to skip `filterByContent` — free-text queries from a bot search
       command are often looser than a clean movie title and may want the
       unfiltered set.
     - Return each result with a **magnet URI already constructed**, not just
       `infoHash` — reuse `scraper/lib/magnetHelper.js` to build
       `magnet:?xt=urn:btih:<hash>&dn=<title>&tr=<trackers>` server-side, so
       the bot doesn't need to duplicate that logic. Also include
       `title, infoHash, seeders, leechers, size (bytes), provider, quality,
       codec, source, languages`.
     - Respect the existing early-return / hard-timeout behavior in
       `scrapeAll` — don't add a second timeout layer on top.
   - `torrent.providers` — returns `listProviders()` output (id + name list),
     so the bot can build a provider picker UI dynamically instead of a
     hardcoded list.
   - `torrent.health` — trivial liveness/version response, same info as the
     existing `GET /health`.

3. **Auth**: this service will be network-reachable from the bot's container,
   so add a shared-secret check, mirroring the pattern tgdl already uses for
   its own aria2c RPC secret (`ARIA2_SECRET` in `core.py`) — e.g. require a
   `secret` field in `params` (as aria2 does by convention) OR an
   `Authorization: Bearer <token>` header (simpler for HTTP-level middleware —
   prefer this, checked before the JSON-RPC method dispatch). Read the token
   from an env var, e.g. `RPC_SHARED_SECRET`. Return a proper JSON-RPC error
   (code `-32001`, "Unauthorized") on mismatch, not a raw 401 (keep the
   response body valid JSON-RPC for `/rpc` specifically).

4. Keep the existing `GET /streams/:type/:id`, `GET /providers`, `GET /health`,
   `/prewarm*` REST routes working unmodified — this is additive, not a
   replacement of the existing REST API.

5. Update `scraper/Dockerfile` if needed (it should already be fine — no new
   runtime deps required beyond what's in `package.json`) and add a
   `docker-compose.yml` service block (or a snippet the user can paste into
   tgdl's own `docker-compose.yml`) running this as a sidecar:
   `magnetio-scraper` service, exposing only to the internal Docker network
   (no public port), with `RPC_SHARED_SECRET` and any Redis cache URL
   (`scraper/lib/cache.js` — check if Redis/Keyv is already wired for caching;
   if so keep using it, it'll make repeat searches fast) passed through env.

6. Write a short `scraper/RPC.md` documenting the JSON-RPC method signatures,
   example curl/JSON-RPC request/response pairs for `torrent.search`, and the
   auth header.

## Part B — Replace tgdl's indexer layer with the new RPC service

Work only inside tgdl's `app/downloader/aria2c/torrent/`. This is a rip-and-
replace: the goal is one search backend, not a stack of fallbacks.

1. **Delete** the following, since Magnetio's 22 providers supersede all of
   them:
   - `app/downloader/aria2c/torrent/indexers/apibay.py`
   - `app/downloader/aria2c/torrent/indexers/torrents_csv.py`
   - `app/downloader/aria2c/torrent/indexers/nyaa.py`
   - `app/downloader/aria2c/torrent/indexers/yts.py`
   - The `search_prowlarr()` function in `search.py`, and the `prowlarr`
     python dependency reference in `pyproject.toml`/`uv.lock` if it's not
     used anywhere else in the codebase (grep first to confirm).
   - Any `SEARCH_API_LINK`-branch logic in `search_torrents()` and
     `initiate_search_tools()`.
   - Remove `prowlarr_url`, `prowlarr_api_key`, `search_api_link`, and
     `torrent_public_indexers` from `app/config.py` (grep the whole repo for
     each of these names first — including `handlers/`, `docs/`, `.env.example`,
     `README.md`, `docker-compose.yml` — and remove every reference, not just
     the `config.py` field, so nothing dangles).

2. Replace `app/downloader/aria2c/torrent/indexers/__init__.py` with a much
   simpler module that no longer fans out to multiple scrapers — dedup/sort is
   now Magnetio's job server-side (`scrapeAll`'s existing `deduplicate()`), and
   there's only one source. It can be reduced to a thin re-export of the
   Magnetio client, or removed entirely with `search.py` calling the client
   module directly — pick whichever leaves less dead scaffolding.

3. Add `app/downloader/aria2c/torrent/magnetio_client.py` — the sole search
   backend. An async function, e.g.
   `async def search_torrents_rpc(query: str, limit: int, providers: list[str] | None, strict: bool) -> list[dict[str, Any]]`,
   using `aiohttp` (already a dependency — see the existing usage pattern that
   was in `search_prowlarr`/`initiate_search_tools` in `search.py` before
   removal) to POST a JSON-RPC 2.0 `torrent.search` request to the sidecar,
   and map its response fields into tgdl's existing result dict shape (used
   downstream by `format_search_results_html` and the Telegraph renderer):
   `{"name": ..., "size": <human-readable via format_bytes()>, "seeders": ...,
   "leechers": ..., "magnet": ..., "torrent": None, "url": ...}`.
   - Timeout: use `settings.magnetio_rpc_timeout`.
   - If the RPC call fails (connection error, timeout, non-2xx, or a
     JSON-RPC `error` object in the response), raise a clear exception up to
     the caller rather than silently returning `[]` — since there's no more
     fallback tier, the handler needs to surface "search backend unavailable"
     to the user instead of a misleading "no results found" (see Part C for
     exactly how this should surface in `torrent_search.py`).

4. Rewrite `search_torrents()` in `search.py` to be a thin wrapper:
   resolve `site`/`method` params (still needed for the provider-picker UX in
   `handlers/torrent_search.py`) into the `providers` list to pass through to
   `magnetio_client.search_torrents_rpc()`, call it, return the result. Delete
   the multi-tier `if/elif` logic entirely — there's only one path now.

5. Add new settings to `app/config.py` (replacing the ones removed in step 1):
   - `magnetio_rpc_url: str` — e.g. `http://magnetio-scraper:8080/rpc`.
     Make this **required** (no `| None` default) since it's now the only
     search backend — fail fast at startup with a clear error if unset,
     rather than letting `/torsearch` silently do nothing at runtime.
   - `magnetio_rpc_secret: str | None`
   - `magnetio_rpc_timeout: int` (default e.g. 20)
   - `magnetio_search_limit: int` (default e.g. 50) — replaces the old
     `search_limit` field if that was Prowlarr-specific; keep it if it's
     generically used elsewhere.

6. `SITES` (in `search.py`, consumed by `handlers/torrent_search.py`'s
   `build_search_keyboard`) should now be populated **exclusively** from
   Magnetio's `torrent.providers` RPC method, called once at startup in
   `initiate_search_tools()`. Delete the old `SEARCH_API_LINK`
   `/api/v1/sites` fetch and the `{"public": "Public Indexers"}` default —
   if the RPC call for providers fails at startup, log an error and let
   `SITES` stay empty (the handler already treats `SITES` being falsy/short
   as "just search everything," which is a reasonable degraded state), but
   don't crash the whole bot on a slow sidecar during startup.

7. Do **not** modify `app/downloader/aria2c/torrent/core.py` (the aria2c
   daemon/download RPC client) or anything under `app/downloader/telegram/`,
   `app/downloader/direct/`, `app/manager/` — this task is search/indexer-
   layer only. The existing aria2c JSON-RPC download flow already accepts
   whatever magnet URI comes back from `search_torrents()` unchanged.

## Part C — Production-readiness checklist

- Unit tests: mirror the existing patterns in tgdl's `tests/` directory for
  the new `magnetio_client.py` module (mock the aiohttp response: success,
  timeout, JSON-RPC error object, malformed response) and for the new `/rpc`
  route in Magnetio's scraper (there may not be existing JS tests — add a
  minimal one with whatever test runner, if any, is already implied by
  `package.json`'s devDependencies; if none exists, a simple supertest-based
  smoke test is fine).
- Add a Docker healthcheck to the `magnetio-scraper` sidecar service pointing
  at `GET /health`.
- Update tgdl's `README.md` / `docs/` with the new env vars
  (`MAGNETIO_RPC_URL`, `MAGNETIO_RPC_SECRET`, `MAGNETIO_RPC_TIMEOUT`) and a
  short "how it fits together" diagram/paragraph (bot → JSON-RPC → scraper
  sidecar → 22 providers → magnet → bot's own aria2c JSON-RPC daemon →
  download).
- Log every RPC failure at `warning`/`error` level with the upstream error
  message. Since there's no fallback tier anymore, `handle_torrent_search` /
  `handle_torrent_search_callback` in `torrent_search.py` must distinguish
  "search backend unreachable/errored" from "search backend returned zero
  results" and show the user a distinct, honest message for each (e.g.
  `"⚠️ Search backend is unavailable right now, try again shortly."` vs
  `"No results found for <query>."`) — don't let a sidecar outage look like a
  bad search term to the user.
- Add a startup check: when tgdl boots, have `initiate_search_tools()` call
  `torrent.health` once and log a clear warning (not a crash) if the sidecar
  isn't reachable yet, so operators immediately see in logs that search is
  degraded, without blocking bot startup entirely (downloads via direct
  link/existing magnet should still work even if search is down).
- Rate-limit / concurrency-limit awareness: Magnetio's `scrapeAll` already
  caps concurrent provider calls via `p-limit` — no changes needed there, but
  make sure tgdl's client sets a request timeout comfortably above Magnetio's
  own `SCRAPER_HARD_TIMEOUT_MS` (default ~27s) so it doesn't cut the request
  off prematurely.
- Update/remove any tests under tgdl's `tests/` directory that cover the
  deleted Prowlarr/apibay/nyaa/yts/torrents_csv code paths, and replace them
  with tests for `magnetio_client.py` (mock the aiohttp RPC call: success,
  timeout, JSON-RPC error object, malformed response).

## Migration note for existing deployments

Document in the README/CHANGELOG that this is a **breaking config change**:
`PROWLARR_URL`, `PROWLARR_API_KEY`, `SEARCH_API_LINK`, and
`TORRENT_PUBLIC_INDEXERS` env vars are no longer read and can be removed from
existing `.env`/`docker-compose.yml` files; `MAGNETIO_RPC_URL` (and optionally
`MAGNETIO_RPC_SECRET`) must be set or the bot will fail to start.

## Explicit non-goals

- No debrid integration of any kind (Magnetio's `scraper/` has none to begin
  with — keep it that way).
- No changes to Magnetio's `addon/` (Stremio manifest/addon logic) or `site/`
  (web frontend) — out of scope, don't deploy them.
- No changes to tgdl's aria2c download daemon, file management, uploader, or
  any non-search handler.
- No fallback search backend — this is intentionally a single point of
  failure for search, traded for a much larger provider set and one code
  path to maintain. If you want resilience later, that's a separate task
  (e.g. running two Magnetio RPC sidecars behind a simple round-robin/retry
  in `magnetio_client.py`), not a reintroduction of the old scrapers.

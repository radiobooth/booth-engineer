# Booth DJ API, version 0

Everything Booth Engineer says to the Booth DJ service, and everything it hears back. Booth Engineer only
makes outbound HTTPS requests; nothing on your network listens. Bodies are JSON unless noted.

After pairing, every call below carries `Authorization: Bearer <device token>`. The token is kept in
Booth Engineer's local config file, readable only by you. Errors come back as `{"error": "..."}` with an
HTTP status.

## Pairing

1. `POST /v0/pair/start` `{"name": "linus"}` (what to call this machine; it defaults to the host name)
   → `{"code": "ABCD-2345", "poll_token": "...", "expires_in": 600, "pair_url": "https://..."}`.
   Booth Engineer shows the code; you enter it on the Booth page on your phone.
2. `POST /v0/pair/claim` `{"poll_token": "..."}`, every few seconds:
   `202 {"status": "waiting"}` until you've entered the code, then `200 {"device_token": "..."}` once,
   or `410` when the code expired.

## Check-in

`POST /v0/checkin` `{"version": "0.0.1"}` (Booth Engineer's version), about once a minute.

```json
{
  "next_checkin_s": 10,
  "shows": [
    {"show_id": "show_...", "status": "queued", "action": "send_catalog",
     "catalog_url": "/v0/shows/show_.../catalog"},
    {"show_id": "show_...", "status": "making"},
    {"show_id": "show_...", "status": "ready", "action": "deliver", "title": "...",
     "files": {"show.json": "https://signed-url", "breaks/01.mp3": "https://signed-url"}}
  ]
}
```

`next_checkin_s` is 60 when nothing is going on and 10 while a show is in progress.

## Sending the catalog for a show

`PUT <catalog_url>` with a [`catalog`](catalog.schema.json), gzip-compressed (`Content-Encoding: gzip`).
It is sent only when you have asked for a show, and Booth DJ keeps it in memory just long enough to make
that one show. It is never stored. → `202`, or `409` if it was already sent.

## Fetching and delivering a show

Booth Engineer downloads each file in `files` from its signed URL (these requests carry no token), checks
every break against its `sha256` in [`show.json`](show-package.schema.json), and delivers it to your music
server. Then it reports how that went:

`POST /v0/shows/{show_id}/result` with `{"ok": true, "playlist": "Playlist title"}` or
`{"ok": false, "error": "What went wrong"}` → `204`. Booth DJ deletes its copy of the package after this.

## What Booth DJ does with the rest

Show requests come from the Booth page on your phone, not from Booth Engineer. A show that gets no catalog
within an hour fails, and a package nobody fetches is deleted after 7 days.

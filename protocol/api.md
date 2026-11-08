# Booth DJ API, version 0

Everything Booth Engineer says to the Booth DJ service, and everything it hears back. Booth Engineer only
makes outbound HTTPS requests (plain HTTP only to a DJ on localhost, for development); nothing on your
network can connect in. (The app's own page listens on 127.0.0.1 only: this computer, never the network.) Bodies are JSON unless noted.

After pairing, every call below carries `Authorization: Bearer <device token>`. The token is kept in
Booth Engineer's local config file, readable only by you. Errors come back as `{"error": "..."}` with an
HTTP status.

## Pairing

Pairing starts on your phone, where you're signed in. The Booth page gives you a code (`ABCD-2345`) that
works once, for 10 minutes; asking for a new one cancels the old one. You type it into `booth pair`, which
trades it for this machine's device token:

`POST /v0/pair` `{"code": "ABCD-2345", "name": "linus"}` (`name` is what to call this machine; it defaults
to the host name) → `200 {"device_token": "...", "name": "linus"}`, or `404` when the code is wrong, used or
expired.

This is the only call made without a token. It creates nothing unless the code is right, so nobody can
block pairing for others by sending made-up requests.

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

`next_checkin_s` is 60 when nothing is going on and 10 while a show is in progress. The Engineer keeps it between 5 and 3600 s, and treats a reply whose `shows` isn't a list of objects with a `show_id` as a failed check-in.

## Sending the catalog for a show

`PUT <catalog_url>` with a [`catalog`](catalog.schema.json), gzip-compressed (`Content-Encoding: gzip`).
It is sent only when you have asked for a show, and Booth DJ keeps it in memory just long enough to make
that one show. It is never stored. → `202`, or `409` if it was already sent.

## Fetching and delivering a show

Booth Engineer downloads each file in `files` from its signed URL (these requests carry no token), checks
every break against its `sha256` in [`show.json`](show-package.schema.json), and delivers it to your music
server. Then it reports how that went:

`POST /v0/shows/{show_id}/result` with `{"ok": true, "playlist": "Playlist title"}` or
`{"ok": false, "error": "Delivery failed on this machine; ..."}` → `204`. The error sent is always that fixed
sentence: the real reason can name local folders or your Plex address, so it stays in Booth Engineer's own
log. Booth DJ deletes its copy of the package after this. If the report itself doesn't get through, Booth
Engineer sends it again on the next check-in without delivering the show twice.

## Asking for shows from Booth's page

Shows are asked for on the Booth page on your phone, or on Booth's own page on this computer. Booth's page
asks through Booth Engineer, with the device token, exactly as the phone page does:

`GET /v0/me` → the DJs and voices to pick from (`roster`) and the show time left (`allowance`); the reply also
names your account and its paired computers.

`GET /v0/shows` → `{"shows": [...], "allowance": {...}}`: your shows, newest first, with their status
(`queued`, `making`, `ready`, `delivered`, `failed`, `expired`).

`POST /v0/shows` with what you typed: `{"prompt": "Rainy drive home", "minutes": 40, "dj": "penrose",
"voice": "A", "dj_name": "", "station": ""}` → `201` with the new show, `400` with what to fix, or `429`
when it doesn't fit your show time. Booth Engineer remembers the choices (not the prompt) in its local config
for next time.

A show asked for this way is made from this computer's library and delivered here: Booth DJ asks only this
Booth Engineer for its catalog, and lists it with `"for_computer": "<this machine's name>"` while it waits.
Booth's page only asks while Booth is on the air.

Nothing else is sent: no catalog goes with a request. It's sent later, on a check-in, as above.

## What Booth DJ does with the rest

A show that gets no catalog within an hour fails, and a package nobody fetches is deleted after 7 days.

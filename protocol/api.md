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

### Sharing one Booth Engineer

Someone with their own Radio Booth account can share your Booth Engineer (**Add another person** on Booth's
page). They get a pairing code on their phone, signed in as themselves, and Booth Engineer trades it with the
same `POST /v0/pair`, under this computer's name with " (shared)" after it. Booth Engineer then keeps one device token per account in
its config file, and makes every call below once per account, each with that account's token: separate
check-ins, catalogs, deliveries and show lists, so each account's shows and show time stay its own. It reads
`GET /v0/me` with the new token to learn the account's name. Booth DJ sees an ordinary paired Booth Engineer
on each account and needs nothing else.

All of their shows are made from this computer's library and go into the same Plex, with this computer's Plex
sign-in, so the playlist title starts with the person's name ("Jennifer: Rainy drive home"). That name is
added on this computer; the playlist title reported back in the delivery result includes it. If you pick
their Plex user on Booth's page, Booth Engineer then shares each of their new playlists with that user, as
"Grant Access" in Plex Web does; Booth DJ isn't involved. What that sends to plex.tv is in
[README.md](README.md#plex-sign-in-during-setup).

## Check-in

`POST /v0/checkin` `{"version": "0.0.1", "delivers_to": "plex"}` about once a minute: Booth Engineer's
version, and where it puts finished shows, `"plex"` (a Plex playlist) or `"playlist"` (a playlist file in the
Booth shows folder, for music in a plain folder), so Booth DJ's pages can say where a show arrives.
`delivers_to` is optional; versions before 0.3.0 don't send it.

When a show asked for is held back on this computer, the check-in also says why, by show id:
`"waiting": {"show_...": "library_scanning"}` while Plex is still scanning the music library, or
`"reading_folder"` while Booth is still reading the music folder. Those two codes are all it ever says, and
only about a show Booth DJ asked for the catalog of, so the phone page can say what the show waits for. A show
missing from `waiting` isn't held back (or the Engineer is older than 0.5.7, which never sends it).

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

If this computer can't read its library for the show in a way that asking again won't fix (Plex answers with
a reply Booth can't read, every time), Booth Engineer gives up after three tries and says so:
`POST /v0/shows/{show_id}/result` with `{"ok": false, "error": "Booth couldn't read the music library on this
machine; ..."}` (a fixed sentence; the reason stays in Booth's log) → `204`, and the show fails, so the
listener's next show can go ahead. `409` if the show isn't waiting on this computer's catalog. Anything that
may pass (Plex off, or refusing the sign-in) is tried until the show times out, as below.

While Plex is still scanning the music library (its sections list says `refreshing`), Booth Engineer waits up
to 10 minutes for the scan to end, then makes the show from the songs Plex has read so far. If it has none
Booth can use yet, it keeps waiting, and after 45 minutes in all fails the show the same way, with the fixed
sentence "Plex was still reading the music library on this computer, with no songs Booth could use yet. ...".

## Fetching and delivering a show

Booth Engineer downloads each file in `files` from its signed URL (these requests carry no token), checks
every break against its `sha256` in [`show.json`](show-package.schema.json), and delivers it to your music
server. Then it reports how that went:

`POST /v0/shows/{show_id}/result` with `{"ok": true, "playlist": "Playlist title"}` or
`{"ok": false, "error": "Delivery failed on this machine; ..."}` → `204`. The error sent is always that fixed
sentence: the real reason can name local folders or your Plex address, so it stays in Booth Engineer's own
log. Booth DJ deletes its copy of the package after this. If the report itself doesn't get through, Booth
Engineer sends it again on the next check-in without delivering the show twice.

## Your shows on Booth's page

`GET /v0/shows` → `{"shows": [...], "allowance": {...}}`: your shows, newest first, with their status
(`queued`, `making`, `ready`, `delivered`, `failed`, `expired`). Booth's page lists the latest few under **Your
shows**, so you can copy or remove the ones on this computer. It asks every 30 seconds while it's open and
Booth is paired and running (every 5 while a show of yours is on its way), and not while the page is hidden.
Now and then it also reads `GET /v0/me` for the account's name, shown under **People**.

Booth's page doesn't ask for shows, rate them or flag breaks: you do that on your phone's Booth page, signed in
to your account. Booth Engineer's device token can't do any of those.

## Downloading a show on your phone

Off unless Radio Booth has switched it on for your account (for testers, for now). For a show delivered to
this computer, the phone page offers **Get the file**: Booth Engineer mixes the show into one MP3 (what
**Make one file** on Booth's page makes, in `Copies/`) and uploads it, so you can listen away from home. This
is the only time audio leaves this computer, and only the show you asked for goes. Nothing is uploaded until
you ask.

A check-in lists the show with `"action": "send_file"` (and its `title`) on the account's Booth Engineer that
delivered it, until the file is in. Booth Engineer then, on a thread of its own so check-ins carry on:

1. `POST /v0/shows/{show_id}/file/making` `{}` → `204`: it's on it.
2. Makes the file, or uses the one already in `Copies/` for that show.
3. `POST /v0/shows/{show_id}/file/upload` `{"bytes": 123456789}` → `{"url": "https://signed-url",
   "headers": {"Content-Type": "audio/mpeg"}}`, then `PUT`s the file to that signed link with those headers and
   no token. The link goes straight to Radio Booth's storage and works for three hours.
4. `POST /v0/shows/{show_id}/file/result` `{"ok": true}`, or `{"ok": false, "error": "Making the file failed
   on this machine; ..."}` (a fixed sentence, as for deliveries; the reason stays in Booth's log) → `204`.

Any of these answers `409` once nobody's waiting for the file any more (it timed out, say), and `result`
answers `422` when the upload didn't arrive whole (Booth DJ has failed the file); Booth Engineer then stops.
Another refusal makes it report the file as failed. If the network drops, it stops too, and starts over when
the next check-in asks again. A file it made only for the phone (not one made on Booth's page) is deleted
from this computer once it's sent.

Only you can download it, signed in on the phone page, through a link that works for 15 minutes. Radio Booth
deletes the file an hour after the first download, or after a day if it isn't downloaded. An ask fails if
this computer doesn't pick it up within 10 minutes, takes more than an hour to make the file, or doesn't finish the
upload before its link runs out. Booth DJ offers **Get the file** only for shows delivered by Booth Engineer
0.5.0 or later.

## What Booth DJ does with the rest

A show that gets no catalog within an hour fails, and a package nobody fetches is deleted after 7 days.

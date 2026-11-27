"""When each track first turned up in a library, as Radio Booth itself saw it.

Music servers stamp every track with the day they first scanned it, which for a library set up in one go is
the day the server was installed, not the day the listener got the record; a folder of files has no such
date at all. So Radio Booth keeps its own, on this machine only (library-seen.json, next to the config):

- The first catalog read of a library is its baseline. Every track in it was "here before Radio Booth kept
  track" and never gets a date.
- A track in a later read that wasn't in any earlier one joined between the two reads: `joined_after` the
  day of the read before, `joined_by` the day of this one.
- A "new" track that's a song already known here (same artist, title and length: a file moved or renamed,
  a Plex rescan that gave it a new id, a second copy; or with its artist or title retagged and moved at
  once) is no news: it keeps the status of the one known. Dates follow songs, never ids alone: an id that
  now holds another song (a rebuilt Plex database) is judged by its new song.
- A track the source found before but couldn't use (a file missing its tags, say) isn't news when it
  becomes usable: the source's `also` ids are remembered too.
- Many new tracks at once (a big rescan or restore) say nothing about when the listener got them, so they
  join the baseline instead.
- Days are the listener's own (this computer's local date), as the DJ says them.

One record per library: its kind, name and where it is (the music folder, or the Plex server), so picking
another folder or server starts a new baseline rather than dating everything in it; a read that mostly
knows the songs of another record of its kind is that library at a new address and carries on with it.
It's shared by
everyone on this computer: it's the library's history, not a person's. Deleting the file starts it over,
with new baselines. Titles never go in it: songs are compared by a short hash of artist, title and length.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from radiobooth import config

VERSION = 1
BULK_MIN = 200  # new tracks in one read, at least, to count as a bulk import...
BULK_SHARE = 0.02  # ... and at least this share of the library


def path() -> Path:
    return config.path().with_name("library-seen.json")


def _stamp(when: datetime) -> str:
    """A time in this computer's own zone, with its offset, so its date is the listener's day too."""
    return when.astimezone().isoformat(timespec="seconds")


def _short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _key(catalog: dict, where: str | None) -> str:
    source = catalog.get("source") or {}
    return f"{source.get('kind', '')}:{source.get('library', '')}:{_short(where or '')}"


def signature(t: dict) -> str:
    """A song as it's recognised again under another id: short hashes of its artist and of its title, and
    its length in two-second steps ("<artist><title>:<steps>")."""
    artist, title = (" ".join(str(t.get(k, "")).casefold().split()) for k in ("artist", "title"))
    return f"{_short(artist)[:6]}{_short(title)[:6]}:{round(t.get('duration_ms', 0) / 2000)}"


def _parts(sig: str) -> tuple[str, str, int] | None:
    name, _, steps = sig.rpartition(":")
    if len(name) != 12 or not steps.lstrip("-").isdigit():
        return None
    return name[:6], name[6:], int(steps)


def _near(sig: str) -> list[str]:
    """The signature and the ones a step shorter and longer, so lengths either side of a step still match."""
    p = _parts(sig)
    if p is None:
        return [sig]
    return [sig, f"{p[0]}{p[1]}:{p[2] - 1}", f"{p[0]}{p[1]}:{p[2] + 1}"]


def same_song(a: str, b: str) -> bool:
    """Whether two signatures are the same song: the same title at much the same length, with the artist
    the same or retagged ("Beatles" to "The Beatles"). The same artist alone isn't enough: their other
    songs often run as long."""
    pa, pb = _parts(a), _parts(b)
    if pa is None or pb is None:
        return a == b
    return abs(pa[2] - pb[2]) <= 1 and pa[1] == pb[1]


def _is_day(v) -> bool:
    if not isinstance(v, str) or len(v) != 10:
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return v[4] == "-" and v[7] == "-"


def _is_time(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _clean(rec) -> dict | None:
    """A library's record as read back, with anything malformed left out; None if it can't be used."""
    if not isinstance(rec, dict) or not (_is_time(rec.get("since")) and _is_day(rec.get("day"))):
        return None
    tracks, joined = rec.get("tracks"), rec.get("joined")
    if not isinstance(tracks, dict) or not isinstance(joined, dict):
        return None
    return {
        "since": rec["since"],
        "day": rec["day"],
        "tracks": {k: v for k, v in tracks.items() if isinstance(k, str) and isinstance(v, str)},
        "joined": {
            k: v
            for k, v in joined.items()
            if isinstance(k, str) and isinstance(v, list) and len(v) == 2 and all(map(_is_day, v))
        },
    }


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, dict):
        return {}
    return {k: rec for k, v in sources.items() if isinstance(k, str) and (rec := _clean(v))}


ADOPT_SHARE = (
    0.9  # of each other's songs a read and another record of its kind share: the same library, moved
)


def _find(sources: dict, key: str, read: dict[str, str]) -> str | None:
    """The record for this library: its own key, or else the record of the same kind whose songs and this
    read's mostly agree (each holds at least ADOPT_SHARE of the other's): the same library at a new
    address (a Plex server reached another way, a drive mounted elsewhere), not a part of it widened."""
    if key in sources:
        return key
    kind = key.split(":", 1)[0] + ":"
    mine = {x for sig in read.values() for x in _near(sig)}
    best, most = None, 0.0
    for k, rec in sources.items():
        if not k.startswith(kind):
            continue
        # By songs, never ids alone: two Plex databases hand out the same small numbers to different songs.
        theirs = [sig for sig in rec["tracks"].values() if sig]
        if not theirs or not read:
            continue
        sigs = set(theirs)
        share = min(
            sum(any(x in sigs for x in _near(sig)) for sig in read.values()) / len(read),
            sum(sig in mine for sig in theirs) / len(theirs),
        )
        if share >= ADOPT_SHARE and share > most:
            best, most = k, share
    return best


def watch(
    catalog: dict, where: str | None = None, when: datetime | None = None, also: Iterable[str] = ()
) -> dict:
    """Note a fresh, whole read of the catalog's library (`where`: its folder or server; `also`: ids of
    tracks the source found but couldn't use, which aren't news when they become usable); its record:
    {"since": the baseline read, "day": this read's local day, "tracks": {id: signature, or "" for one
    not usable yet}, "joined": {id: [after day, by day]}}."""
    when = when or datetime.now(UTC)
    today = when.astimezone().date().isoformat()
    sources, key = _load(), _key(catalog, where)
    read = {t["id"]: signature(t) for t in catalog["tracks"]}
    found = _find(sources, key, read)
    rec = sources.pop(found) if found else None
    if rec is None:
        rec = {"since": _stamp(when), "day": today, "tracks": dict(read), "joined": {}}
    else:
        known, joined = rec["tracks"], rec["joined"]
        before = dict(joined)  # each id's status as it was, by the song it held
        by_song: dict[str, str] = {}
        for i, sig in known.items():
            if sig:
                by_song.setdefault(sig, i)
        # Known ids this read doesn't have: a song among them may be back under a new id and new tags.
        gone = [(i, sig) for i, sig in known.items() if sig and i not in read]
        unsettled = []  # ids to judge by their songs
        for i, sig in read.items():
            old = known.get(i)
            if old and not same_song(old, sig):  # the id holds another song now (ids handed out again)
                joined.pop(i, None)
                unsettled.append(i)
            elif i not in known:  # ("" is a track seen before that couldn't be used: no news)
                unsettled.append(i)
        arrived = []
        for i in unsettled:
            sig = read[i]
            twin = next((o for x in _near(sig) if (o := by_song.get(x)) is not None and o != i), None)
            if twin is None:  # retagged and moved at once: a song that went missing from this read
                twin = next((g for g, gsig in gone if same_song(gsig, sig)), None)
                if twin is not None:
                    gone = [(g, gsig) for g, gsig in gone if g != twin]
            if twin is not None:
                if twin in before:
                    joined[i] = before[twin]
            else:
                arrived.append(i)
        if len(arrived) < max(BULK_MIN, BULK_SHARE * len(read)):
            for i in arrived:
                joined[i] = [min(rec["day"], today), today]
        known.update(read)  # each song as it's tagged now, so a later move still matches it
        rec["day"] = today
    for i in also:
        rec["tracks"].setdefault(i, "")
    sources[key] = rec
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomically(p, json.dumps({"version": VERSION, "sources": sources}) + "\n")
    return rec


def annotate(
    catalog: dict,
    fresh: bool = True,
    where: str | None = None,
    when: datetime | None = None,
    also: Iterable[str] = (),
) -> dict:
    """The catalog with `history_since` and each arrival's `joined_after` and `joined_by`. `fresh`: this
    is a whole, new read of the library, noted first (see `watch`); otherwise only what earlier reads
    saw. Never fails a show: any trouble with the file sends the catalog without arrivals."""
    try:
        if fresh:
            rec = watch(catalog, where, when, also)
        else:
            sources = _load()
            read = {t["id"]: signature(t) for t in catalog["tracks"]}
            rec = sources.get(_find(sources, _key(catalog, where), read) or "")
    except Exception:  # noqa: BLE001 - arrivals are a nicety; the show goes on without them
        rec = None
    if not rec:
        return catalog
    catalog["history_since"] = rec["since"]
    for t in catalog["tracks"]:
        if j := rec["joined"].get(t["id"]):
            t["joined_after"], t["joined_by"] = j
    return catalog

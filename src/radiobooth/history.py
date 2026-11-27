"""Radio Booth's own play history: which shows delivered to this machine had which tracks.

Kept on this machine only, next to the config file (history.json), and yours to read or delete. For each
track it keeps how many shows had it and the latest ones (when, which show, its title, where in the running
order). It travels to Booth DJ only inside a show's catalog (see `annotate`), and Booth DJ keeps it no
longer than the catalog itself. Deleting the file starts the history over. Each other person sharing this
computer has their own (history-<id>.json), so one person's shows don't keep tracks out of another's.

This, not a music server's play counts, is what DJs may say about the listener's history with a track: a
music server only counts its own plays, and a folder of files has none. Earlier versions kept only when a
track was last in a show; such a track carries over as one show with `floor` set, since it may have been
in more.

The catalog also carries when each track joined the library, from `arrivals`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from radiobooth import arrivals, config

VERSION = 2
KEEP = 10  # latest shows kept per track (the count goes on past it)
SENT = 3  # latest shows sent per track, newest first


def path(person: str | None = None) -> Path:
    """This computer's own account's history, or (`person`: an id from config.people) another person's."""
    return config.path().with_name(f"history-{person}.json" if person else "history.json")


def stamp(when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_time(v) -> bool:
    if not isinstance(v, str) or "T" not in v.upper():
        return False
    try:
        return datetime.fromisoformat(v.upper().replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _entry(value) -> dict | None:
    """One track's history as kept, from either version of the file; None if it can't be read. {"count":
    shows that had it, "floor": True when count may be short, "shows": [{"at", ...}, newest first]}"""
    if _is_time(value):  # version 1: when it was last in a show
        return {"count": 1, "floor": True, "shows": [{"at": value}]}
    if not isinstance(value, dict):
        return None
    shows = value.get("shows")
    if not isinstance(shows, list):
        return None
    shows = [s for s in shows if isinstance(s, dict) and _is_time(s.get("at"))]
    for s in shows:
        if "title" in s and not (isinstance(s["title"], str) and s["title"].strip()):
            del s["title"]
    count = value.get("count")
    if not shows or not isinstance(count, int) or isinstance(count, bool) or count < len(shows):
        return None
    out = {"count": count, "shows": sorted(shows, key=lambda s: s["at"], reverse=True)[:KEEP]}
    if value.get("floor") is True:
        out["floor"] = True
    return out


def load(person: str | None = None) -> dict[str, dict]:
    """track id -> its history (see `_entry`). A missing or unreadable file is an empty history."""
    try:
        data = json.loads(path(person).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, dict):
        return {}
    return {k: e for k, v in tracks.items() if isinstance(k, str) and k and (e := _entry(v))}


def last_at(entry: dict) -> str:
    return entry["shows"][0]["at"]


def record(
    track_ids: Iterable[str],
    when: datetime | None = None,
    person: str | None = None,
    show: str | None = None,
    title: str | None = None,
) -> Path:
    """Note that these tracks, in this running order, were just in a delivered show (`show`: its id, so the
    same show delivered again isn't counted twice; `title`: what it's called)."""
    tracks = load(person)
    at = stamp(when)
    for slot, t in enumerate((t for t in track_ids if isinstance(t, str) and t), start=1):
        entry = tracks.setdefault(t, {"count": 0, "shows": []})
        if show and any(s.get("show") == show for s in entry["shows"]):
            continue
        played = {"at": at, "slot": slot}
        if show:
            played["show"] = show
        if title and title.strip():
            played["title"] = title.strip()
        entry["count"] += 1
        entry["shows"] = sorted([played, *entry["shows"]], key=lambda s: s["at"], reverse=True)[:KEEP]
    p = path(person)
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomically(p, json.dumps({"version": VERSION, "tracks": tracks}, sort_keys=True) + "\n")
    return p


def record_package(package: dict, when: datetime | None = None, person: str | None = None) -> Path:
    """Note the tracks of a show package that was just delivered."""
    tracks = [i.get("track_id") for i in package.get("items", []) if i.get("type") == "track"]
    return record(tracks, when, person, show=package.get("show_id"), title=package.get("title"))


def annotate(
    catalog: dict,
    person: str | None = None,
    fresh: bool = True,
    where: str | None = None,
    also: Iterable[str] = (),
) -> dict:
    """The catalog with Radio Booth's own history on its tracks: for each track that was in this person's
    shows, `in_shows` (with `in_shows_at_least` when that's a floor), `last_in_show_at` and `recent_shows`;
    and the library's arrivals (`arrivals.annotate`). `fresh`: this is a whole, new read of the library,
    so tracks new since the last one are noted as arrivals (not for a library Plex is still reading, or a
    look at the catalog that sends nothing). `where`: the library's folder or server; `also`: ids the
    source found but couldn't use (see `arrivals`)."""
    seen = load(person)
    for t in catalog["tracks"]:
        if entry := seen.get(t["id"]):
            t["in_shows"] = entry["count"]
            if entry.get("floor"):
                t["in_shows_at_least"] = True
            t["last_in_show_at"] = last_at(entry)
            t["recent_shows"] = [{k: s[k] for k in ("at", "title") if k in s} for s in entry["shows"][:SENT]]
    return arrivals.annotate(catalog, fresh=fresh, where=where, also=also)

"""Which tracks have been in Booth shows delivered to this machine, so new shows can skip them.

Kept on this machine only, next to the config file (history.json), and yours to read or delete. It travels
to Booth DJ only inside a show's catalog, as each track's `last_in_show_at`, and Booth DJ keeps it no longer
than the catalog itself. Deleting the file starts the history over. Each other person sharing this computer
has their own (history-<id>.json), so one person's shows don't keep tracks out of another's.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from radiobooth import config


def path(person: str | None = None) -> Path:
    """This computer's own account's history, or (`person`: an id from config.people) another person's."""
    return config.path().with_name(f"history-{person}.json" if person else "history.json")


def stamp(when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load(person: str | None = None) -> dict[str, str]:
    """track id -> when it was last in a delivered show. A missing or unreadable file is an empty history."""
    try:
        data = json.loads(path(person).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, dict):
        return {}
    return {k: v for k, v in tracks.items() if isinstance(k, str) and k and isinstance(v, str)}


def record(track_ids: Iterable[str], when: datetime | None = None, person: str | None = None) -> Path:
    """Note that these tracks were just in a delivered show."""
    tracks = load(person)
    at = stamp(when)
    tracks.update({t: at for t in track_ids if isinstance(t, str) and t})
    p = path(person)
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomically(p, json.dumps({"version": 1, "tracks": tracks}, indent=0, sort_keys=True) + "\n")
    return p


def record_package(package: dict, when: datetime | None = None, person: str | None = None) -> Path:
    """Note the tracks of a show package that was just delivered."""
    tracks = (i.get("track_id") for i in package.get("items", []) if i.get("type") == "track")
    return record(tracks, when, person)


def annotate(catalog: dict, person: str | None = None) -> dict:
    """The catalog with `last_in_show_at` on each track that has been in a show here (for that person)."""
    seen = load(person)
    for t in catalog["tracks"]:
        if t["id"] in seen:
            t["last_in_show_at"] = seen[t["id"]]
    return catalog

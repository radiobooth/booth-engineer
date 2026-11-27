"""When each track first turned up in a library, as Radio Booth itself saw it.

Music servers stamp every track with the day they first scanned it, which for a library set up in one go is
the day the server was installed, not the day the listener got the record; a folder of files has no such
date at all. So Radio Booth keeps its own, on this machine only (library-seen.json, next to the config):

- The first catalog read of a library is its baseline. Every track in it was "here before Radio Booth kept
  track" and never gets a date.
- A track in a later read that wasn't in any earlier one joined between the two reads: `joined_after` the
  day of the read before, `joined_by` the day of this one.
- Many new tracks at once (a moved or rescanned library, a restored backup, a newly picked folder) say
  nothing about when the listener got them, so they join the baseline instead.

One record per library (its kind and name), shared by everyone on this computer: it's the library's
history, not a person's. Deleting the file starts it over, with a new baseline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from radiobooth import config

VERSION = 1
BULK_MIN = 200  # new tracks in one read, at least, to count as a bulk import...
BULK_SHARE = 0.02  # ... and at least this share of the library


def path() -> Path:
    return config.path().with_name("library-seen.json")


def _stamp(when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _key(catalog: dict) -> str:
    source = catalog.get("source") or {}
    return f"{source.get('kind', '')}:{source.get('library', '')}"


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sources = data.get("sources") if isinstance(data, dict) else None
    return {k: v for k, v in (sources or {}).items() if _valid(v)} if isinstance(sources, dict) else {}


def _valid(rec) -> bool:
    return (
        isinstance(rec, dict)
        and isinstance(rec.get("since"), str)
        and isinstance(rec.get("read"), str)
        and isinstance(rec.get("before"), list)
        and isinstance(rec.get("joined"), dict)
    )


def watch(catalog: dict, when: datetime | None = None) -> dict:
    """Note a fresh, whole read of the catalog's library; its record: {"since": the baseline read, "read":
    this read, "before": ids from the baseline, "joined": {id: [after day, by day]}}."""
    sources = _load()
    key, now = _key(catalog), _stamp(when)
    ids = [t["id"] for t in catalog["tracks"]]
    rec = sources.get(key)
    if rec is None:
        rec = {"since": now, "read": now, "before": sorted(set(ids)), "joined": {}}
    else:
        known = set(rec["before"]) | rec["joined"].keys()
        new = sorted({i for i in ids if i not in known})
        if len(new) >= max(BULK_MIN, BULK_SHARE * len(ids)):
            rec["before"] = sorted(set(rec["before"]) | set(new))
        else:
            for i in new:
                rec["joined"][i] = [rec["read"][:10], now[:10]]
        rec["read"] = now
    sources[key] = rec
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomically(p, json.dumps({"version": VERSION, "sources": sources}) + "\n")
    return rec


def annotate(catalog: dict, fresh: bool = True, when: datetime | None = None) -> dict:
    """The catalog with `history_since` and each arrival's `joined_after` and `joined_by`. `fresh`: this
    is a whole, new read of the library, noted first (see `watch`); otherwise only what earlier reads
    saw. Never fails a show: trouble with the file sends the catalog without arrivals."""
    try:
        rec = watch(catalog, when) if fresh else _load().get(_key(catalog))
    except OSError:
        rec = None
    if not rec:
        return catalog
    catalog["history_since"] = rec["since"]
    for t in catalog["tracks"]:
        if (j := rec["joined"].get(t["id"])) and isinstance(j, list) and len(j) == 2:
            t["joined_after"], t["joined_by"] = j
    return catalog

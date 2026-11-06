"""Keep "added" dates only where they say when music joined the collection.

Music servers stamp every track with the day they first scanned it. For a library that was imported in one
go, that is the day the server was set up, not the day the listener got the record, and a DJ saying "you
added this in March 2011" about an album owned since 1992 sounds wrong. Bulk imports are dropped here so
the service only hears about real adds:

- the first IMPORT_DAYS after the earliest add: the library's initial import;
- any later day that added a big share of the library at once: a move, a rescan or a restored backup.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

IMPORT_DAYS = 14
BURST_MIN = 200  # tracks in one day, at least
BURST_SHARE = 0.02  # of the library, at least


def bulk_days(tracks: list[dict]) -> set[str]:
    """The YYYY-MM-DD days whose adds look like bulk imports."""
    days = Counter(t["added_at"][:10] for t in tracks if t.get("added_at"))
    if not days:
        return set()
    cutoff = (date.fromisoformat(min(days)) + timedelta(days=IMPORT_DAYS)).isoformat()
    burst = max(BURST_MIN, BURST_SHARE * len(tracks))
    return {d for d, n in days.items() if d < cutoff or n >= burst}


def drop_bulk_dates(tracks: list[dict]) -> int:
    """Remove added_at from tracks that came in with a bulk import. Returns how many were removed."""
    bulk = bulk_days(tracks)
    dropped = 0
    for t in tracks:
        if t.get("added_at", "")[:10] in bulk:
            del t["added_at"]
            dropped += 1
    return dropped

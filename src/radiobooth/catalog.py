"""Check each catalog track against protocol/catalog.schema.json before it leaves this machine.

One odd file in a folder of thousands must never stop a show, so this works per track: a track missing
something the catalog requires is left out (and counted), a malformed optional detail is dropped from its
track, and a field the protocol doesn't list is dropped too, so only what protocol/ documents is sent.

TRACK mirrors the schema's track properties (minus descriptions); a test keeps the two the same. The app
ships without a JSON Schema library, so this checks only the keywords those properties use.
"""

from __future__ import annotations

from datetime import datetime

_STRING, _INT, _BOOL = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
_LIST = {"type": "array", "items": {"type": "string"}}
_YEAR = {"type": "integer", "minimum": 1800, "maximum": 2200}
_TIME = {"type": "string", "format": "date-time"}

REQUIRED = ["id", "title", "artist", "duration_ms"]
TRACK: dict[str, dict] = {
    "id": {"type": "string", "minLength": 1},
    "title": _STRING,
    "artist": _STRING,
    "artists": _LIST,
    "album_artist": _STRING,
    "album": _STRING,
    "disc_number": {"type": "integer", "minimum": 1},
    "track_number": {"type": "integer", "minimum": 1},
    "year": _YEAR,
    "original_year": _YEAR,
    "compilation": _BOOL,
    "genres": _LIST,
    "composers": _LIST,
    "label": _STRING,
    "duration_ms": {"type": "integer", "minimum": 1},
    "added_at": _TIME,
    "play_count": {"type": "integer", "minimum": 0},
    "last_played_at": _TIME,
    "last_in_show_at": _TIME,
    "rating": {"type": "number", "minimum": 0, "maximum": 1},
    "musicbrainz_id": _STRING,
    "musicbrainz_release_group_id": _STRING,
    "musicbrainz_artist_id": _STRING,
    "from_path": _BOOL,
    "sonic": {"type": "object", "required": ["provider"], "properties": {"provider": _STRING}},
}


def _is_type(v, kind: str) -> bool:
    if kind == "string":
        return isinstance(v, str)
    if kind == "boolean":
        return isinstance(v, bool)
    if kind == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if kind == "array":
        return isinstance(v, list)
    if kind == "object":
        return isinstance(v, dict)
    raise ValueError(f"unknown schema type {kind!r}")


def _date_time(v: str) -> bool:
    try:
        when = datetime.fromisoformat(v.upper().replace("Z", "+00:00"))
    except ValueError:
        return False
    return "T" in v.upper() and when.tzinfo is not None  # RFC 3339 needs a time and a zone


def fits(v, spec: dict) -> bool:
    """Whether `v` matches this (small) schema."""
    if not _is_type(v, spec["type"]):
        return False
    if "minLength" in spec and len(v) < spec["minLength"]:
        return False
    if "minimum" in spec and v < spec["minimum"]:
        return False
    if "maximum" in spec and v > spec["maximum"]:
        return False
    if spec.get("format") == "date-time" and not _date_time(v):
        return False
    if "items" in spec and not all(fits(x, spec["items"]) for x in v):
        return False
    if any(k not in v for k in spec.get("required", [])):
        return False
    return all(fits(v[k], s) for k, s in spec.get("properties", {}).items() if k in v)


def check_track(t) -> tuple[dict | None, str | None]:
    """(the track as it may be sent, None) or (None, why it can't be)."""
    if not isinstance(t, dict):
        return None, "not a track"
    for key in REQUIRED:
        if key not in t:
            return None, f"no {key}"
        if not fits(t[key], TRACK[key]):
            return None, f"a malformed {key}"
    return {k: v for k, v in t.items() if k in TRACK and fits(v, TRACK[k])}, None


def check(catalog: dict) -> tuple[dict, int, str | None]:
    """The catalog with each track checked: (catalog, how many tracks were left out, the first reason).
    A repeated id keeps its first track."""
    tracks, ids, skipped, first = [], set(), 0, None
    for i, t in enumerate(catalog.get("tracks", [])):
        clean, why = check_track(t)
        if clean is not None and clean["id"] in ids:
            clean, why = None, "a repeated id"
        if clean is None:
            skipped += 1
            first = first or f"track {i}: {why}"
            continue
        ids.add(clean["id"])
        tracks.append(clean)
    return catalog | {"tracks": tracks}, skipped, first

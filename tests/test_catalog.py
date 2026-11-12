"""Each catalog track is checked against the protocol before it leaves the machine."""

import json
from pathlib import Path

from radiobooth import catalog

SCHEMA = json.loads((Path(__file__).parent.parent / "protocol" / "catalog.schema.json").read_text("utf-8"))
TRACK_SCHEMA = SCHEMA["$defs"]["track"]


def strip(spec):
    if isinstance(spec, dict):
        return {k: strip(v) for k, v in spec.items() if k != "description"}
    return spec


def test_the_check_mirrors_the_schema():
    assert strip(TRACK_SCHEMA["properties"]) == catalog.TRACK
    assert TRACK_SCHEMA["required"] == catalog.REQUIRED


def test_tracks_are_checked_one_by_one():
    good = {"id": "1", "title": "T", "artist": "A", "duration_ms": 1000}
    tracks = [
        good
        | {"year": 1700, "genres": ["Rock", 3], "path": "/home/me/x.flac", "last_in_show_at": "2026-11-01"},
        {"id": "2", "title": "No artist", "duration_ms": 1000},
        good | {"title": "Repeated id"},
        good | {"id": "3", "duration_ms": 0},
        "not a track",
        good | {"id": "4", "sonic": {"provider": "plex"}, "last_played_at": "2026-11-01T10:00:00Z"},
    ]
    checked, skipped, first = catalog.check({"protocol": "radiobooth/catalog@0", "tracks": tracks})
    assert checked["tracks"] == [
        good,
        good | {"id": "4", "sonic": {"provider": "plex"}, "last_played_at": "2026-11-01T10:00:00Z"},
    ]
    assert skipped == 4 and first == "track 1: no artist"

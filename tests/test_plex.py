import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from radiobooth.sources import plex

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "protocol" / "catalog.schema.json").read_text())

ALBUMS = [
    {"ratingKey": "900", "title": "Electriclarryland", "year": 1996, "Genre": [{"tag": "Alternative"}]},
]
TRACKS = [
    {
        "ratingKey": 48211,
        "parentRatingKey": "900",
        "title": "Pepper",
        "grandparentTitle": "Butthole Surfers",
        "parentTitle": "Electriclarryland",
        "index": 5,
        "parentIndex": 1,
        "duration": 297000,
        "addedAt": 1240089240,
        "viewCount": 12,
        "lastViewedAt": 1730000000,
        "userRating": 8.0,
        "Guid": [{"id": "mbid://0d3cbd4f-0000-0000-0000-000000000000"}],
        "Media": [{"Part": [{"file": "/home/someone/Music/Butthole Surfers/05 Pepper.flac"}]}],
    },
    {
        "ratingKey": 51007,
        "title": "Some Duet",
        "grandparentTitle": "Various Artists",
        "originalTitle": "L7",
        "duration": 175000,
        "parentYear": 0,
        "index": 0,
    },
    {"ratingKey": 1, "title": "No length", "grandparentTitle": "Nobody"},
]


class FakePlex:
    def __init__(self, sections=None, page_size=1):
        self.sections = sections or [{"key": "3", "type": "artist", "title": "Music"}]
        self.page_size = page_size

    def get(self, path, params=None):
        if path == "/library/sections":
            return {"MediaContainer": {"Directory": [*self.sections, {"key": "1", "type": "movie"}]}}
        items = TRACKS if params["type"] == plex.TRACK else ALBUMS
        start = params["X-Plex-Container-Start"]
        page = items[start : start + self.page_size]
        return {"MediaContainer": {"Metadata": page, "totalSize": len(items)}}


def test_track_mapping():
    t = plex.to_track(TRACKS[0], {"year": 1996, "genres": ["Alternative"]})
    assert t == {
        "id": "48211",
        "title": "Pepper",
        "artist": "Butthole Surfers",
        "album": "Electriclarryland",
        "disc_number": 1,
        "track_number": 5,
        "year": 1996,
        "genres": ["Alternative"],
        "duration_ms": 297000,
        "added_at": "2009-04-18T21:14:00Z",
        "play_count": 12,
        "last_played_at": "2024-10-27T03:33:20Z",
        "rating": 0.8,
        "musicbrainz_id": "0d3cbd4f-0000-0000-0000-000000000000",
    }


def test_track_artist_differs_from_album_artist_and_bad_numbers_dropped():
    t = plex.to_track(TRACKS[1])
    assert t["artist"] == "L7" and t["album_artist"] == "Various Artists"
    assert "year" not in t and "track_number" not in t


def test_catalog_pages_skips_and_validates():
    catalog, skipped = plex.build_catalog(FakePlex())
    assert [t["id"] for t in catalog["tracks"]] == ["48211", "51007"]
    assert skipped == 1
    Draft202012Validator(SCHEMA).validate(catalog)


def test_no_file_paths_leave():
    catalog, _ = plex.build_catalog(FakePlex(page_size=500))
    assert "/home/someone" not in json.dumps(catalog)


def test_library_choice():
    two = [{"key": "3", "type": "artist", "title": "Music"}, {"key": "4", "type": "artist", "title": "Vinyl"}]
    with pytest.raises(plex.PlexError, match="several"):
        plex.build_catalog(FakePlex(two))
    catalog, _ = plex.build_catalog(FakePlex(two), library="Vinyl")
    assert catalog["source"]["library"] == "Vinyl"
    with pytest.raises(plex.PlexError, match="No music library"):
        plex.build_catalog(FakePlex(two), library="Tapes")


def test_non_json_answer_explains_the_port(monkeypatch):
    class Resp:
        headers = {"Content-Type": "text/html"}

        def read(self):
            return b"<html>NAS login</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(plex.urllib.request, "urlopen", lambda req, timeout: Resp())
    with pytest.raises(plex.PlexError, match="32400"):
        plex.PlexClient("http://nas.local", "t").get("/library/sections")

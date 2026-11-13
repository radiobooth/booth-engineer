import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from radiobooth.sources import plex

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "protocol" / "catalog.schema.json").read_text())

ARTISTS = [
    {
        "ratingKey": "800",
        "title": "Butthole Surfers",
        "Guid": [{"id": "mbid://2f2d3d1c-5b3a-4a8e-9c1d-7e6f5a4b3c2d"}],
    },
    {
        "ratingKey": "801",
        "title": "Various Artists",
        "Guid": [{"id": "mbid://89ad4ac3-39f7-470e-963a-56509c546377"}],
    },
]
ALBUMS = [
    {
        "ratingKey": "900",
        "title": "Electriclarryland",
        "parentTitle": "Butthole Surfers",
        "year": 1995,
        "originallyAvailableAt": "1996-01-01",  # Plex's time-zone slip: the album is from 1996
        "studio": "Capitol Records",
        "Genre": [{"tag": "Alternative"}],
    },
    {"ratingKey": "901", "title": "Some Comp", "parentTitle": "Various Artists", "studio": "[no label]"},
]
TRACKS = [
    {
        "ratingKey": 48211,
        "parentRatingKey": "900",
        "grandparentRatingKey": "800",
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
        "parentRatingKey": "901",
        "grandparentRatingKey": "801",
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
        items = {plex.TRACK: TRACKS, plex.ALBUM: ALBUMS, plex.ARTIST: ARTISTS}[params["type"]]
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


def test_album_and_artist_details_from_plex():
    catalog, _ = plex.build_catalog(FakePlex(page_size=500))
    pepper, duet = catalog["tracks"]
    assert pepper["year"] == 1996  # the release date's year, not Plex's slipped one
    assert pepper["label"] == "Capitol Records"
    assert pepper["musicbrainz_artist_id"] == "2f2d3d1c-5b3a-4a8e-9c1d-7e6f5a4b3c2d"
    assert "compilation" not in pepper and "musicbrainz_id" not in pepper
    assert duet["compilation"] is True and "label" not in duet  # "[no label]" is no label
    assert "musicbrainz_artist_id" not in duet  # L7's track: the album artist's id isn't theirs


def test_only_real_musicbrainz_ids_are_sent():
    plex_own = {"Guid": [{"id": "mbid://0d3cbd4f-1234-3abc-8def-000000000000"}]}  # UUID version 3
    assert plex._musicbrainz(plex_own) is None
    assert plex._musicbrainz({"Guid": [{"id": "plex://artist/5d07bbfc403c6402904a5ec4"}]}) is None


@pytest.mark.parametrize(
    ("year", "date", "want"),
    [(1998, "1999-01-01", 1999), (1971, "1971-03-01", 1971), (1990, "1971-01-01", 1990), (2001, None, 2001)],
)
def test_album_year_mends_only_the_new_year_slip(year, date, want):
    assert plex._album_year({"year": year, "originallyAvailableAt": date}) == want


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


def test_index_can_skip_the_breaks_library():
    two = [
        {"key": "4", "type": "artist", "title": "Music"},
        {"key": "7", "type": "artist", "title": "Radio Booth"},
    ]
    catalog, _ = plex.build_catalog(FakePlex(two), exclude="Radio Booth")
    assert catalog["source"]["library"] == "Music"


def test_a_refused_sign_in_says_to_sign_in_again(monkeypatch):
    def refuse(req, timeout):
        raise plex.urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(plex.urllib.request, "urlopen", refuse)
    with pytest.raises(plex.PlexAuthError, match="Sign in to Plex again"):
        plex.PlexClient("http://nas.local:32400", "stale").get("/library/sections")


def test_a_song_file_cut_off_partway_is_an_error(tmp_path):
    import socketserver
    import threading

    class Short(socketserver.StreamRequestHandler):
        def handle(self):
            while self.rfile.readline() not in (b"\r\n", b""):
                pass
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n" + b"x" * 10
            )

    with socketserver.TCPServer(("127.0.0.1", 0), Short) as server:
        threading.Thread(target=server.handle_request, daemon=True).start()
        client = plex.PlexClient(f"http://127.0.0.1:{server.server_address[1]}", "t", timeout=5)
        with pytest.raises(plex.PlexError, match="partway"):
            client.download("/library/parts/1/1/file.flac", tmp_path / "song.flac")

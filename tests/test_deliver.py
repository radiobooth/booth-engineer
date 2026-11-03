import hashlib
import json

import pytest

from radiobooth.cli import main
from radiobooth.sources.plex import PlexError
from radiobooth.targets import plex as target


def make_show(tmp_path):
    show = tmp_path / "show"
    (show / "breaks").mkdir(parents=True)
    items = []
    for n, tracks in ((1, ["101", "102"]), (2, ["103"]), (3, [])):
        f = show / "breaks" / f"{n:02d}.mp3"
        f.write_bytes(b"mp3-%d" % n)
        items.append(
            {
                "type": "break",
                "id": f"b{n:02d}",
                "file": f"breaks/{f.name}",
                "duration_ms": 20000,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "transcript": "Hi.",
            }
        )
        items += [{"type": "track", "track_id": t} for t in tracks]
    package = {
        "protocol": "radiobooth/show-package@0",
        "show_id": "show_abcdef123456",
        "request_id": "r",
        "created_at": "2026-11-03T05:02:00Z",
        "title": "Wipers On, Long Way Home",
        "dj": {"personality": "penrose", "voice": "A"},
        "items": items,
    }
    (show / "show.json").write_text(json.dumps(package))
    return show


class FakePlex:
    """A Plex server whose scanner finds files after `scans_needed` listings."""

    def __init__(self, scans_needed=2):
        self.calls, self.scans_needed, self.listings = [], scans_needed, 0
        self.folder = None

    def get(self, path, params=None):
        return self.request("GET", path, params)

    def request(self, method, path, params=None):
        self.calls.append((method, path, params))
        if path == "/library/sections":
            return {
                "MediaContainer": {
                    "Directory": [
                        {
                            "key": "4",
                            "type": "artist",
                            "title": "Music",
                            "Location": [{"path": "/volume1/audio/collection"}],
                        },
                        {
                            "key": "7",
                            "type": "artist",
                            "title": "Radio Booth",
                            "Location": [{"path": "/volume1/audio/radiobooth"}],
                        },
                        {"key": "1", "type": "movie", "title": "Movies"},
                    ]
                }
            }
        if path.endswith("/refresh"):
            self.folder = "2026-11-03-wipers-on-long-way-home-123456"
            return {}
        if path == "/library/sections/7/all":
            self.listings += 1
            if self.listings < self.scans_needed or params["X-Plex-Container-Start"]:
                return {"MediaContainer": {"Metadata": [], "totalSize": 0}}
            meta = [
                {
                    "ratingKey": 900 + n,
                    "Media": [{"Part": [{"file": f"/volume1/audio/radiobooth/{self.folder}/{n:02d}.mp3"}]}],
                }
                for n in (1, 2, 3)
            ]
            return {"MediaContainer": {"Metadata": meta, "totalSize": 3}}
        if path == "/identity":
            return {"MediaContainer": {"machineIdentifier": "abc123"}}
        if path == "/playlists":
            return {"MediaContainer": {"Metadata": [{"ratingKey": "5555", "title": params["title"]}]}}
        raise AssertionError(path)


def test_deliver_copies_scans_and_builds_playlist_in_order(tmp_path):
    show, dest, plex = make_show(tmp_path), tmp_path / "nas", FakePlex()
    dest.mkdir()
    result = target.deliver(plex, show, "Radio Booth", dest, sleep=lambda s: None)
    folder = "2026-11-03-wipers-on-long-way-home-123456"
    assert sorted(p.name for p in (dest / folder).iterdir()) == ["01.mp3", "02.mp3", "03.mp3"]
    refresh = next(c for c in plex.calls if c[1].endswith("/refresh"))
    assert refresh[1] == "/library/sections/7/refresh"
    assert refresh[2] is None  # whole library: Plex ignored folder-scoped scans in practice
    method, _, params = plex.calls[-1]
    assert method == "POST" and params["type"] == "audio" and params["smart"] == 0
    assert params["uri"] == (
        "server://abc123/com.plexapp.plugins.library/library/metadata/901,101,102,902,103,903"
    )
    assert (result.playlist_key, result.tracks, result.breaks) == ("5555", 3, 3)


def test_deliver_gives_up_when_plex_never_sees_the_files(tmp_path):
    show, dest = make_show(tmp_path), tmp_path / "nas"
    dest.mkdir()
    with pytest.raises(PlexError, match="didn't pick up"):
        target.deliver(FakePlex(scans_needed=99), show, "Radio Booth", dest, wait=0, sleep=lambda s: None)


def test_deliver_checks_files_and_library(tmp_path):
    show = make_show(tmp_path)
    (show / "breaks" / "02.mp3").write_bytes(b"changed")
    with pytest.raises(PlexError, match="checksum"):
        target.load_package(show)
    with pytest.raises(PlexError, match="No Plex library"):
        target.section_named(FakePlex(), "Tapes")
    with pytest.raises(PlexError, match="isn't a music library"):
        target.section_named(FakePlex(), "Movies")


def test_cli_deliver_needs_settings(monkeypatch, tmp_path, capsys):
    for var in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(var, raising=False)
    assert main(["deliver", str(tmp_path)]) == 1
    assert "PLEX_URL" in capsys.readouterr().err
    monkeypatch.setenv("PLEX_URL", "http://x")
    monkeypatch.setenv("PLEX_TOKEN", "t")
    assert main(["deliver", str(tmp_path), "--library", "Radio Booth", "--dest", str(tmp_path / "nope")]) == 1
    assert "isn't a folder" in capsys.readouterr().err

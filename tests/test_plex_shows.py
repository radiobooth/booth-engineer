"""Plex shows found again from their id: copied whole, mixed into one file, or removed."""

import json
import shutil

import pytest
from mutagen.mp3 import MP3
from test_render import tone

from radiobooth.sources.plex import PlexError
from radiobooth.targets import playlist
from radiobooth.targets import plex as target

SHOW = "show_abcdef123456"
FOLDER = "2026-11-03-wipers-on-long-way-home-123456"


class PlexWithPlaylists:
    """A Plex server holding one Booth show's playlist (and another of the user's own)."""

    def __init__(self, server_files, folder=FOLDER):
        self.files = server_files  # part key -> a file standing in for the server's copy
        self.calls, self.deleted = [], []
        self.playlists = {
            "77": [self._song(1, "One", 3), self._song(2, "Two", 4)],  # someone's own playlist
            "5555": [
                self._break(folder, 1),
                self._song(1, "One", 3),
                self._song(2, "Two", 4),
                self._break(folder, 2),
                self._song(3, "Three", 2, missing=True),
            ],
        }

    def _song(self, n, title, track, missing=False):
        return {
            "ratingKey": str(100 + n),
            "title": title,
            "grandparentTitle": "The Band",
            "parentRatingKey": "50",
            "parentIndex": 1,
            "index": track,
            "duration": 5000,
            "Media": [{"Part": [{"key": f"/library/parts/{n}/1/file.flac", "file": f"/music/{title}.flac"}]}],
        } | (
            {"Media": [{"Part": [{"key": f"/library/parts/{n}/1/gone.flac", "file": "/music/x.flac"}]}]}
            if missing
            else {}
        )

    def _break(self, folder, n):
        return {
            "ratingKey": str(900 + n),
            "title": f"Break {n}",
            "grandparentTitle": "Penrose",
            "duration": 3000,
            "Media": [
                {
                    "Part": [
                        {
                            "key": f"/library/parts/9{n}/1/file.mp3",
                            "file": f"/nas/radiobooth/{folder}/{n:02d}.mp3",
                        }
                    ]
                }
            ],
        }

    def get(self, path, params=None):
        return self.request("GET", path, params)

    def request(self, method, path, params=None):
        self.calls.append((method, path, params))
        if path == "/playlists" and method == "GET":
            listed = [
                {"ratingKey": k, "title": "Wipers On, Long Way Home" if k == "5555" else "Mine"}
                for k in self.playlists
            ]
            return {"MediaContainer": {"Metadata": listed}}
        if path.startswith("/playlists/") and path.endswith("/items"):
            key = path.split("/")[2]
            if key not in self.playlists:
                raise PlexError("Plex returned HTTP 404")
            return {"MediaContainer": {"Metadata": self.playlists[key]}}
        if method == "DELETE" and path.startswith("/playlists/"):
            key = path.split("/")[2]
            self.deleted.append(key)
            self.playlists.pop(key)
            return {}
        if path == "/library/sections":
            return {"MediaContainer": {"Directory": [{"key": "7", "type": "artist", "title": "Radio Booth"}]}}
        if path == "/library/sections/7/refresh":
            return {}
        raise AssertionError(path)

    def download(self, part_key, dest):
        if part_key not in self.files:
            raise PlexError("Plex returned HTTP 404 for a song's file")
        shutil.copyfile(self.files[part_key], dest)


@pytest.fixture
def plex_show(tmp_path):
    dest = tmp_path / "radiobooth"
    breaks = dest / FOLDER
    breaks.mkdir(parents=True)
    tone(breaks / "01.mp3", "libmp3lame", 3, 220, 0.3, rate=24000)
    tone(breaks / "02.mp3", "libmp3lame", 3, 330, 0.3, rate=24000)
    server = tmp_path / "server"
    server.mkdir()
    files = {}
    for n in (1, 2):
        files[f"/library/parts/{n}/1/file.flac"] = tone(server / f"{n}.flac", "flac", 5, 400 + 100 * n, 0.3)
    return PlexWithPlaylists(files), dest, tmp_path / "Booth shows" / "Copies"


def test_an_older_show_is_found_by_its_breaks_and_noted(plex_show):
    plex, dest, _ = plex_show
    assert target.shows_here(dest, [SHOW, "show_other99"]) == {SHOW}
    show = target.find_show(plex, dest, SHOW, "Wipers On")
    assert show.playlist_key == "5555" and show.title == "Wipers On, Long Way Home"
    note = json.loads((dest / FOLDER / target.NOTE).read_text(encoding="utf-8"))
    assert note["playlist_key"] == "5555"
    plex.calls.clear()
    assert target.find_show(plex, dest, SHOW).playlist_key == "5555"
    assert [c[1] for c in plex.calls] == ["/playlists/5555/items"]  # the note saves the search


def test_copy_fetches_songs_from_plex_and_breaks_from_their_folder(plex_show):
    plex, dest, copies = plex_show
    made = target.copy_out(plex, dest, copies, SHOW)
    names = sorted(p.name for p in made.folder.iterdir())
    assert names == [
        "01 Break 1.mp3",
        "02 The Band - One.flac",
        "03 The Band - Two.flac",
        "04 Break 2.mp3",
        "Wipers On, Long Way Home.m3u8",
    ]
    assert made.missing == 1  # Three wasn't on the server
    assert playlist.show_of(made.folder / "Wipers On, Long Way Home.m3u8") == SHOW


def test_one_file_mixes_a_plex_show_and_cleans_up(plex_show):
    plex, dest, copies = plex_show
    seen = []
    made = target.one_file(plex, dest, copies, SHOW, progress=lambda *p: seen.append(p))
    assert made.path == copies / "Wipers On, Long Way Home.mp3" and made.missing == 1
    mp3 = MP3(str(made.path))
    assert str(mp3.tags["TPE1"]) == "Penrose"
    chapters = sorted(mp3.tags.getall("CHAP"), key=lambda f: f.start_time)
    assert [str(c.sub_frames["TIT2"]) for c in chapters] == [
        "Break 1",
        "The Band - One",
        "The Band - Two",
        "Break 2",
    ]
    assert sorted(p.name for p in copies.iterdir()) == ["Wipers On, Long Way Home.mp3"]  # fetched songs gone
    assert seen[-1][0] == seen[-1][1]


def test_remove_deletes_the_playlist_breaks_and_copies_only(plex_show):
    plex, dest, copies = plex_show
    target.copy_out(plex, dest, copies, SHOW)
    assert target.remove(plex, dest, "Radio Booth", SHOW)
    playlist.drop_copies(copies, SHOW)
    assert plex.deleted == ["5555"] and "77" in plex.playlists
    assert not (dest / FOLDER).exists() and list(copies.iterdir()) == []
    assert ("GET", "/library/sections/7/refresh", None) in plex.calls
    assert not target.remove(plex, dest, "Radio Booth", SHOW)


def test_a_show_whose_playlist_was_deleted_in_plex(plex_show):
    plex, dest, copies = plex_show
    del plex.playlists["5555"]
    with pytest.raises(PlexError, match="playlist isn't in Plex"):
        target.copy_out(plex, dest, copies, SHOW)
    assert target.remove(plex, dest, "Radio Booth", SHOW)  # its breaks still go
    assert not (dest / FOLDER).exists()


def test_two_unnoted_folders_with_the_same_tail_are_left_alone(plex_show):
    _, dest, _ = plex_show
    (dest / "2026-11-04-other-123456").mkdir()
    assert target.show_folder(dest, SHOW) is None

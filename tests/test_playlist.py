"""Shows from a music folder: a playlist per show, its breaks beside it, the music left where it is."""

import json
import time

import pytest
from test_deliver import make_show
from test_folder import tagged

from radiobooth import config, engine, history
from radiobooth.targets import playlist
from radiobooth.targets.plex import PlexError
from radiobooth.websetup import WebSetup, music_ready

MUSIC = {"101": "Talking Heads/Remain in Light/01.flac", "102": "Björk/Post/02.flac", "103": "X/Y/03.flac"}


def music_folder(tmp_path):
    root = tmp_path / "music"
    for rel in MUSIC.values():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"audio")
    return root


def lookup_in(table):
    def lookup(track_id):
        rel = table.get(track_id)
        return (
            (rel, {"artist": "Artist " + track_id, "title": "Song\n" + track_id, "duration_ms": 61499})
            if rel
            else None
        )

    return lookup


def test_a_show_is_a_playlist_of_the_music_where_it_is_and_the_breaks(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "Booth shows"
    out.mkdir()
    done = playlist.deliver(show, out, music, lookup_in(MUSIC), prefix="Jennifer: ")
    assert (done.title, done.tracks, done.breaks, done.missing) == (
        "Jennifer: Wipers On, Long Way Home",
        3,
        3,
        0,
    )
    assert done.playlist == out.resolve() / "Jennifer - Wipers On, Long Way Home.m3u8"
    lines = done.playlist.read_text(encoding="utf-8").splitlines()
    breaks = out.resolve() / "breaks" / "2026-11-03-wipers-on-long-way-home-123456"
    assert lines[:5] == [
        "#EXTM3U",
        "#PLAYLIST:Jennifer: Wipers On, Long Way Home",
        "#BOOTH-SHOW:show_abcdef123456",
        "#EXTINF:20,Booth - Break 1",
        "breaks/2026-11-03-wipers-on-long-way-home-123456/01.mp3",
    ]
    # Relative to the playlist, so it plays wherever the folders are reached (another computer, a NAS).
    assert lines[5:7] == ["#EXTINF:61,Artist 101 - Song 101", "../music/" + MUSIC["101"]]
    assert "../music/" + MUSIC["102"] in lines  # names as they are, accents and all
    assert all((out / x).is_file() for x in lines if not x.startswith("#"))
    assert sorted(p.name for p in breaks.iterdir()) == ["01.mp3", "02.mp3", "03.mp3"]
    assert (breaks / "01.mp3").read_bytes() == b"mp3-1"


def test_delivering_again_rewrites_the_same_playlist_and_another_show_gets_its_own(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "out"
    out.mkdir()
    first = playlist.deliver(show, out, music, lookup_in(MUSIC))
    again = playlist.deliver(show, out, music, lookup_in(MUSIC))
    assert again.playlist == first.playlist
    package = json.loads((show / "show.json").read_text())
    (show / "show.json").write_text(json.dumps(package | {"show_id": "show_other999999"}))
    other = playlist.deliver(show, out, music, lookup_in(MUSIC))
    assert other.playlist.name == "Wipers On, Long Way Home (2).m3u8"
    (out / "Mine.m3u8").write_text("#EXTM3U\nsomething of the listener's own\n")
    assert [s.show_id for s in playlist.shows(out)] == ["show_other999999", "show_abcdef123456"]


def test_tracks_gone_from_the_folder_are_left_out_and_counted(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "out"
    out.mkdir()
    (music / MUSIC["102"]).unlink()
    table = MUSIC | {"103": "../../outside.flac"}  # never a file outside the music folder
    (tmp_path / "outside.flac").write_bytes(b"x")
    done = playlist.deliver(show, out, music, lookup_in(table))
    assert (done.tracks, done.missing) == (1, 2)
    with pytest.raises(playlist.PlaylistError, match="None of this show's tracks"):
        playlist.deliver(show, out, music, lambda _: None)


def test_a_damaged_package_is_refused_before_anything_is_written(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "out"
    out.mkdir()
    (show / "breaks" / "01.mp3").write_bytes(b"swapped")
    with pytest.raises(PlexError, match="checksum"):
        playlist.deliver(show, out, music, lookup_in(MUSIC))
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ('AC/DC: "Live" <at> the Ritz?', "AC-DC - Live at the Ritz"),
        ("CON", "Booth show CON"),
        ("...", "Booth show"),
        ("Late night\tdrive. ", "Late night drive"),
        ("Sigur Rós ✶ " + "x" * 200, ("Sigur Rós ✶ " + "x" * 200)[:100]),
    ],
)
def test_playlist_names_every_system_accepts(title, name):
    assert playlist.file_name(title) == name


def test_removing_a_show_deletes_its_playlist_and_breaks_never_music(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "out"
    out.mkdir()
    done = playlist.deliver(show, out, music, lookup_in(MUSIC))
    assert playlist.remove(out, "show_abcdef123456")
    assert not done.playlist.exists() and not done.folder.exists()
    assert all((music / rel).exists() for rel in MUSIC.values())
    assert not playlist.remove(out, "show_abcdef123456")


def test_paths_stay_full_when_the_music_is_on_another_windows_drive(monkeypatch, tmp_path):
    def other_drive(path, start):
        raise ValueError("path is on mount 'M:', start on mount 'C:'")

    monkeypatch.setattr(playlist.os.path, "relpath", other_drive)
    assert playlist._ref(tmp_path / "x.flac", tmp_path / "out") == str(tmp_path / "x.flac")


def test_a_relative_path_never_reads_as_a_comment(tmp_path):
    assert playlist._ref(tmp_path / "#1 Hits" / "a.mp3", tmp_path) == "./#1 Hits/a.mp3"


def test_shows_written_with_full_paths_are_still_removed(tmp_path):
    out = tmp_path / "out"
    breaks = out.resolve() / "breaks" / "old-show"
    breaks.mkdir(parents=True)
    (breaks / "01.mp3").write_bytes(b"x")
    (out / "Old.m3u8").write_text(f"#EXTM3U\n#BOOTH-SHOW:show_old\n{breaks / '01.mp3'}\n")
    assert playlist.remove(out, "show_old")
    assert not breaks.exists()


def test_a_show_copied_to_a_folder_is_numbered_files_in_playing_order(tmp_path):
    show, music, out = make_show(tmp_path), music_folder(tmp_path), tmp_path / "out"
    out.mkdir()
    (music / MUSIC["103"]).unlink()
    playlist.deliver(show, out, music, lookup_in(MUSIC | {"103": "X/Y/03.flac"}), prefix="Jennifer: ")
    (music / MUSIC["102"]).unlink()  # gone after the show was made
    seen = []
    made = playlist.copy_out(out, "show_abcdef123456", lambda done, total: seen.append((done, total)))
    assert made.folder == out.resolve() / "Copies" / "Jennifer - Wipers On, Long Way Home"
    assert (made.files, made.missing) == (4, 1)
    assert seen[0] == (0, 4) and seen[-1] == (4, 4)
    names = sorted(p.name for p in made.folder.iterdir())
    assert names == [
        "01 Booth - Break 1.mp3",
        "02 Artist 101 - Song 101.flac",
        "03 Booth - Break 2.mp3",
        "04 Booth - Break 3.mp3",
        "Jennifer - Wipers On, Long Way Home.m3u8",
    ]
    assert (made.folder / "02 Artist 101 - Song 101.flac").read_bytes() == b"audio"
    text = (made.folder / "Jennifer - Wipers On, Long Way Home.m3u8").read_text(encoding="utf-8")
    assert "#EXTINF:61,Artist 101 - Song 101\n02 Artist 101 - Song 101.flac\n" in text
    assert [s.show_id for s in playlist.shows(out)] == ["show_abcdef123456"]  # copies aren't shows

    again = playlist.copy_out(out, "show_abcdef123456")
    assert again.folder == made.folder and not list((out / "Copies").glob(".*"))
    package = json.loads((show / "show.json").read_text())
    (show / "show.json").write_text(json.dumps(package | {"show_id": "show_other999999"}))
    playlist.deliver(show, out, music, lookup_in(MUSIC), prefix="Jennifer: ")
    other = playlist.copy_out(out, "show_other999999")
    assert other.folder.name == "Jennifer - Wipers On, Long Way Home (2)"

    assert playlist.remove(out, "show_abcdef123456")
    assert not made.folder.exists() and other.folder.exists()
    with pytest.raises(playlist.PlaylistError, match="isn't in your Booth shows folder"):
        playlist.copy_out(out, "show_abcdef123456")


def test_a_playlist_pointing_elsewhere_never_deletes_that_folder(tmp_path):
    out, elsewhere = tmp_path / "out", tmp_path / "elsewhere"
    (out / "breaks").mkdir(parents=True)
    elsewhere.mkdir()
    (elsewhere / "01.mp3").write_bytes(b"x")
    (out / "Odd.m3u8").write_text(f"#EXTM3U\n#BOOTH-SHOW:show_x\n{elsewhere / '01.mp3'}\n")
    assert playlist.remove(out, "show_x")
    assert (elsewhere / "01.mp3").exists()


# The whole way through: setup, reading the folder, a show delivered, history kept.


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    for name in ("BOOTH_SOURCE", "BOOTH_MUSIC_FOLDER", "BOOTH_SHOWS_FOLDER"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_setup_with_a_folder_then_a_show_from_it(home):
    music = home / "My Music"
    tagged(music, "Talking Heads/01.flac", TITLE="Once in a Lifetime", ARTIST="Talking Heads")
    tagged(music, "Björk/01.flac", TITLE="Hyperballad", ARTIST="Björk")
    saved = []
    setup = WebSetup(lambda: "https://booth.example", "linus", on_saved=lambda: saved.append(1))
    with pytest.raises(Exception, match="can't find that music folder"):
        setup.use_music_folder(str(home / "nope"), "")
    with pytest.raises(Exception, match="folder of their own"):
        setup.use_music_folder(str(music), str(home))
    setup.use_music_folder(f'"{music}"', str(home / "Booth shows"))
    settings = config.load()
    assert saved and music_ready(settings) and engine.folder_mode(settings)
    assert (home / "Booth shows").is_dir()

    seen = []
    st = engine.station(settings, print, on_scan=lambda *a: seen.append(a))
    catalog = st.catalog()
    assert catalog["source"] == {"kind": "folder", "library": "Music"}
    assert seen[-2:-1] == [(2, 2)] and seen[-1][0].used == 2
    by_title = {t["title"]: t["id"] for t in catalog["tracks"]}

    show = make_show(home)
    package = json.loads((show / "show.json").read_text())
    ids = iter([by_title["Hyperballad"], by_title["Once in a Lifetime"], "gone"])
    for item in package["items"]:
        if item["type"] == "track":
            item["track_id"] = next(ids)
    (show / "show.json").write_text(json.dumps(package))
    assert st.deliver(show) == "Wipers On, Long Way Home"
    text = (home / "Booth shows" / "Wipers On, Long Way Home.m3u8").read_text(encoding="utf-8")
    assert ",Björk - Hyperballad\n" in text
    assert "\n../My Music/Björk/01.flac\n" in text
    assert set(history.load()) == {by_title["Hyperballad"], by_title["Once in a Lifetime"], "gone"}


def test_the_engine_reads_the_folder_in_the_background_with_progress(home):
    music = home / "m"
    for n in range(3):
        tagged(music, f"{n}.flac", TITLE=f"T{n}", ARTIST="A")
    shows = home / "shows"
    shows.mkdir()
    config.update({"music_source": "folder", "music_folder": str(music), "shows_folder": str(shows)})
    e = engine.Engine(echo=False)
    assert e.scan_music()
    deadline = time.monotonic() + 10
    while e.status()["report"] is None and time.monotonic() < deadline:
        time.sleep(0.05)
    status = e.status()
    assert status["scan"] is None and status["report"]["used"] == 3 and not e.busy
    assert any("Used: 3" in line for line in status["report"]["lines"])


def test_scan_progress_counts_the_rate_of_files_read_not_those_already_known():
    e = engine.Engine(echo=False)
    e._scanned(900, 1000)  # 900 known from last time
    e.scan["started"] -= 10
    e._scanned(950, 1000)
    assert e.scan["rate"] == pytest.approx(5, rel=0.05)
    assert e.scan["left_s"] == pytest.approx(10, rel=0.05)


def test_check_in_says_where_shows_go(home):
    from radiobooth.link import Link

    config.update({"server": "https://booth.example", "device_token": "t", "music_source": "folder"})
    config.update({"music_folder": str(home), "shows_folder": str(home / "s")})
    found, _ = engine.desks(config.load(), print, Link)
    link = found[0][0]
    sent = []
    link.post = lambda path, data: (sent.append(data), (200, {"shows": []}))[1]
    link.checkin()
    assert sent[0]["delivers_to"] == "playlist"


def test_music_in_linked_folders_and_decomposed_names_is_found(tmp_path):
    import os
    import unicodedata

    show, music, out = make_show(tmp_path), tmp_path / "music", tmp_path / "out"
    out.mkdir()
    other_drive = tmp_path / "drive2" / "Album"
    other_drive.mkdir(parents=True)
    (other_drive / "01.flac").write_bytes(b"a")
    music.mkdir()
    os.symlink(tmp_path / "drive2", music / "linked")
    decomposed = unicodedata.normalize("NFD", "Björk")
    (music / decomposed).mkdir()
    (music / decomposed / "02.flac").write_bytes(b"b")
    table = {"101": "linked/Album/01.flac", "102": "Björk/02.flac", "103": "C:/x.flac"}
    done = playlist.deliver(show, out, music, lookup_in(table))
    assert (done.tracks, done.missing) == (2, 1)
    assert "../music/linked/Album/01.flac" in done.playlist.read_text(encoding="utf-8").splitlines()


def test_a_folder_copied_from_a_mac_holding_composed_names_is_found(tmp_path):
    import unicodedata

    show, music, out = make_show(tmp_path), tmp_path / "music", tmp_path / "out"
    out.mkdir()
    folder = music / unicodedata.normalize("NFD", "Björk")  # the folder decomposed, the file inside composed
    folder.mkdir(parents=True)
    (folder / "Jóga.flac").write_bytes(b"j")
    done = playlist.deliver(show, out, music, lookup_in({"101": "Björk/Jóga.flac"}))
    assert (done.tracks, done.missing) == (1, 2)
    # A Mac's disk folds the two spellings together and takes either; elsewhere, the one on disk is written.
    (written,) = [x for x in done.playlist.read_text(encoding="utf-8").splitlines() if x.endswith(".flac")]
    assert (out / written).read_bytes() == b"j"


def test_a_show_asked_for_while_the_folder_is_still_being_read_waits_without_holding_check_ins(home):
    config.update({"music_source": "folder", "music_folder": str(home), "shows_folder": str(home / "s")})
    st = engine.station(config.load(), print, reading=lambda: {"done": 5, "total": 10})
    with pytest.raises(engine.FolderBusy, match="still reading"):
        st.catalog()


def test_choosing_another_folder_during_a_read_reads_that_one_next(home, monkeypatch):
    first, second = home / "first", home / "second"
    tagged(first, "1.flac", TITLE="One", ARTIST="A")
    tagged(second, "1.flac", TITLE="Two", ARTIST="B")
    tagged(second, "2.flac", TITLE="Three", ARTIST="B")
    config.update({"music_source": "folder", "music_folder": str(first), "shows_folder": str(home / "s")})
    gate, real = __import__("threading").Event(), engine.read_folder

    def slow(settings, on_scan=None):
        gate.wait(5)
        return real(settings, on_scan)

    monkeypatch.setattr(engine, "read_folder", slow)
    e = engine.Engine(echo=False)
    assert e.scan_music()
    config.update({"music_folder": str(second)})
    assert not e.scan_music(again=True)  # busy: it's read after the first
    gate.set()
    deadline = time.monotonic() + 10
    while (e.report or {}).get("used") != 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert e.report["used"] == 2 and e.report["folder"] == str(second)

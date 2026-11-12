"""The folder source: tags read faithfully from every format, stable ids, and nothing that can't be used."""

import json
import os
import shutil
import unicodedata
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, PCNT, TALB, TCON, TDOR, TDRC, TIT2, TPE1, TPE2, TRCK, TXXX, UFID, Encoding
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from radiobooth.cli import main
from radiobooth.sources import folder, tags

AUDIO = Path(__file__).parent / "audio"
SCHEMA = json.loads((Path(__file__).parent.parent / "protocol" / "catalog.schema.json").read_text("utf-8"))
REC = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
KEY = b"k" * 32


def put(root: Path, rel: str, blank: str = "blank.flac") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(AUDIO / blank, path)
    return path


def id3(path: Path, *frames, version: int = 4) -> Path:
    t = ID3()
    for f in frames:
        t.add(f)
    t.save(path, v2_version=version)
    return path


def vorbis(path: Path, cls=FLAC, **values) -> Path:
    f = cls(path)
    for k, v in values.items():
        f[k] = v
    f.save()
    return path


def scan(root: Path, home: Path, **kw):
    return folder.build_catalog(root, "Music", KEY, home, **kw)


def test_mp3_id3v24_lists_and_musicbrainz(tmp_path):
    p = id3(
        put(tmp_path, "a.mp3", "blank.mp3"),
        TIT2(encoding=3, text="Life During Wartime"),
        TPE1(encoding=3, text=["Talking Heads", "Brian Eno"]),
        TPE2(encoding=3, text="Talking Heads"),
        TALB(encoding=3, text="Fear of Music"),
        TRCK(encoding=3, text="03/11"),
        TDRC(encoding=3, text="2005-10-24"),
        TDOR(encoding=3, text="1979-08-03"),
        TCON(encoding=3, text=["New Wave", "Art Rock"]),
        UFID(owner="http://musicbrainz.org", data=REC.encode()),
        TXXX(encoding=3, desc="MusicBrainz Release Group Id", text=REC.upper()),
    )
    f = tags.read(p).fields
    assert f["artist"] == "Talking Heads & Brian Eno" and f["artists"] == ["Talking Heads", "Brian Eno"]
    assert "album_artist" not in f or f["album_artist"] == "Talking Heads"
    assert (f["track_number"], f["year"], f["original_year"]) == (3, 2005, 1979)
    assert f["genres"] == ["New Wave", "Art Rock"]
    assert f["musicbrainz_id"] == REC and f["musicbrainz_release_group_id"] == REC
    assert 400 < f["duration_ms"] < 1000  # the audio's own length


def test_names_are_never_split_by_guessing(tmp_path):
    """AC/DC is one band; ID3v2.3 can't hold lists, so a "/" there stays as tagged."""
    p = id3(put(tmp_path, "a.mp3", "blank.mp3"), TIT2(encoding=3, text="T"), TPE1(encoding=3, text="AC/DC"))
    assert tags.read(p).fields["artist"] == "AC/DC"
    id3(p, TIT2(encoding=3, text="T"), TPE1(encoding=3, text="Simon & Garfunkel"), version=3)
    f = tags.read(p).fields
    assert f["artist"] == "Simon & Garfunkel" and "artists" not in f


def test_id3v1_genre_numbers_become_names(tmp_path):
    p = id3(put(tmp_path, "a.mp3", "blank.mp3"), TIT2(encoding=3, text="T"), TCON(encoding=3, text="(17)"))
    assert tags.read(p).fields["genres"] == ["Rock"]


def test_mis_encoded_text_is_repaired_only_when_safe(tmp_path):
    p = put(tmp_path, "a.mp3", "blank.mp3")
    id3(p, TIT2(encoding=Encoding.LATIN1, text="BjÃ¶rk"), TPE1(encoding=Encoding.LATIN1, text="Björk"))
    t = tags.read(p)
    assert (t.fields["title"], t.fields["artist"], t.repaired) == ("Björk", "Björk", True)
    # Looks damaged, but isn't valid UTF-8: left as tagged and counted.
    id3(p, TIT2(encoding=Encoding.LATIN1, text="BjÃ¶rk Ã"), TPE1(encoding=3, text="X"))
    t = tags.read(p)
    assert t.fields["title"] == "BjÃ¶rk Ã" and t.garbled and not t.repaired


@pytest.mark.parametrize(
    "blank,cls", [("blank.flac", FLAC), ("blank.ogg", OggVorbis), ("blank.opus", OggOpus)]
)
def test_vorbis_comments(tmp_path, blank, cls):
    p = vorbis(
        put(tmp_path, "a" + Path(blank).suffix, blank),
        cls,
        TITLE="CRΣΣKS",
        ARTIST="Bon Iver",
        ARTISTS=["Bon Iver"],
        DATE="2019",
        ORIGINALYEAR="2019",
        GENRE=["Indie", "indie", "Folk"],
        COMPOSER=["Justin Vernon", "BJ Burton"],
        LABEL="Jagjaguwar",
        COMPILATION="0",
        MUSICBRAINZ_TRACKID=REC,
        MUSICBRAINZ_ALBUMID=REC,
    )
    t = tags.read(p)
    f = t.fields
    assert f["title"] == "CRΣΣKS" and f["year"] == 2019 and "original_year" not in f  # same year: not news
    assert f["genres"] == ["Indie", "Folk"] and f["composers"] == ["Justin Vernon", "BJ Burton"]
    assert f["label"] == "Jagjaguwar" and "compilation" not in f and "artists" not in f
    assert t.release_id == REC and t.lossless == (cls is FLAC)


@pytest.mark.parametrize("blank,lossless", [("blank.m4a", False), ("blank-alac.m4a", True)])
def test_mp4_atoms(tmp_path, blank, lossless):
    f = MP4(p := put(tmp_path, "a.m4a", blank))
    f["©nam"], f["©ART"], f["aART"] = ["Track"], ["Guest"], ["Various Artists"]
    f["trkn"], f["disk"], f["cpil"] = [(7, 12)], [(2, 2)], True
    f["----:com.apple.iTunes:MusicBrainz Track Id"] = [MP4FreeForm(REC.encode())]
    f["----:com.apple.iTunes:LABEL"] = [MP4FreeForm(b"Rhino")]
    f.save()
    t = tags.read(p)
    assert t.fields["album_artist"] == "Various Artists" and t.fields["compilation"] is True
    assert (t.fields["track_number"], t.fields["disc_number"], t.fields["label"]) == (7, 2, "Rhino")
    assert t.fields["musicbrainz_id"] == REC and t.lossless is lossless


def test_wma_and_wav(tmp_path):
    f = ASF(p := put(tmp_path, "a.wma", "blank.wma"))
    f["Title"], f["Author"], f["WM/TrackNumber"], f["WM/Year"] = ["W"], ["A"], [4], ["1999"]
    f.save()
    assert tags.read(p).fields | {"duration_ms": 0} == {
        "title": "W",
        "artist": "A",
        "track_number": 4,
        "year": 1999,
        "duration_ms": 0,
    }
    w = WAVE(p := put(tmp_path, "b.wav", "blank.wav"))
    w.add_tags()
    w.tags.add(TIT2(encoding=3, text="Wave"))
    w.save()
    assert tags.read(p).fields["title"] == "Wave" and tags.read(p).lossless


def test_play_counts_but_no_ratings_or_add_dates(tmp_path):
    p = id3(put(tmp_path, "a.mp3", "blank.mp3"), TIT2(encoding=3, text="T"), PCNT(count=12))
    f = tags.read(p).fields
    assert f["play_count"] == 12 and not {"rating", "added_at", "last_played_at"} & f.keys()


def tagged(root: Path, rel: str, blank="blank.flac", **values) -> Path:
    p = put(root, rel, blank)
    if blank.endswith(".mp3"):
        frames = {"TITLE": TIT2, "ARTIST": TPE1, "ALBUM": TALB, "TRACKNUMBER": TRCK}
        return id3(p, *(frames[k](encoding=3, text=v) for k, v in values.items()))
    return vorbis(p, **values)


def test_folder_catalog_matches_the_protocol_and_sends_no_paths(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "Talking Heads/Remain in Light/01.flac", TITLE="Born Under Punches", ARTIST="Talking Heads")
    tagged(music, "x/y.flac", TITLE="CRΣΣKS", ARTIST="Bon Iver", DATE="2019")
    catalog, report = scan(music, home)
    Draft202012Validator(SCHEMA).validate(catalog)
    assert catalog["source"] == {"kind": "folder", "library": "Music"}
    text = json.dumps(catalog, ensure_ascii=False)
    assert "Remain in Light/01" not in text and ".flac" not in text and str(music) not in text
    assert all("added_at" not in t and "rating" not in t for t in catalog["tracks"])
    assert report.used == 2 and report.files == 2


def test_ids_are_keyed_stable_and_follow_moves(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    a = tagged(music, "A/one.flac", TITLE="One", ARTIST="A")
    tagged(music, "A/two.flac", TITLE="Two", ARTIST="A")
    first = {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]}
    assert first == {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]}  # the same each scan
    assert first["One"] != folder.track_id(b"other key" * 4, "A/one.flac")[:24]  # keyed, so per install
    # A move or rename keeps the id (and so the show history); a new file at the old path gets its own.
    (music / "B").mkdir()
    a.rename(music / "B" / "renamed.flac")
    tagged(music, "A/one.flac", TITLE="New", ARTIST="A")
    after = {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]}
    assert after["One"] == first["One"] and after["Two"] == first["Two"]
    assert after["New"] not in first.values()


def test_retagging_in_place_keeps_the_id(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    p = tagged(music, "a.flac", TITLE="Wrong", ARTIST="A")
    before = scan(music, home)[0]["tracks"][0]["id"]
    vorbis(p, TITLE="Right, after fixing the tags")
    (t,) = scan(music, home)[0]["tracks"]
    assert t["title"].startswith("Right") and t["id"] == before


def test_macos_decomposed_names_give_the_same_id(tmp_path):
    nfd = unicodedata.normalize("NFD", "Björk/Jóga.flac")
    assert folder.relative(tmp_path, tmp_path / nfd) == unicodedata.normalize("NFC", "Björk/Jóga.flac")


def test_changed_files_are_read_again_and_index_is_reused(tmp_path, monkeypatch):
    music, home = tmp_path / "music", tmp_path / "home"
    p = tagged(music, "a.flac", TITLE="Old", ARTIST="A")
    scan(music, home)
    reads = []
    real = tags.read
    monkeypatch.setattr(tags, "read", lambda path: reads.append(path) or real(path))
    assert scan(music, home)[0]["tracks"][0]["title"] == "Old" and reads == []  # nothing changed
    vorbis(p, TITLE="A much longer new title, so the size changes too")
    assert scan(music, home)[0]["tracks"][0]["title"].startswith("A much longer") and len(reads) == 1


def test_names_from_folders_only_for_a_clean_layout(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    put(music, "Pixies/Doolittle/03 Wave of Mutilation.flac")
    put(music, "Downloads/track.flac")
    catalog, report = scan(music, home)
    (t,) = catalog["tracks"]
    assert t | {"id": "x", "duration_ms": 1} == {
        "id": "x",
        "artist": "Pixies",
        "album": "Doolittle",
        "title": "Wave of Mutilation",
        "track_number": 3,
        "duration_ms": 1,
        "from_path": True,
    }
    assert report.skipped[folder.NO_NAMES] == 1 and report.samples[folder.NO_NAMES] == [
        "Downloads/track.flac"
    ]


def test_best_copy_of_a_recording_is_kept(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    names = {"TITLE": "Debaser", "ARTIST": "Pixies", "ALBUM": "Doolittle", "TRACKNUMBER": "1"}
    tagged(music, "mp3/01.mp3", "blank.mp3", **names)
    tagged(music, "flac/01.flac", **names)
    tagged(music, "other/01.flac", **(names | {"ALBUM": "Death to the Pixies"}))  # another album: kept
    catalog, report = scan(music, home)
    assert len(catalog["tracks"]) == 2 and report.duplicates == [("mp3/01.mp3", "flac/01.flac")]


def test_bad_files_are_counted_never_fatal(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "good.flac", TITLE="Good", ARTIST="A")
    (music / "broken.mp3").write_bytes(b"\x00not audio" * 50)
    (music / "album.flac").write_bytes((AUDIO / "blank.flac").read_bytes())
    (music / "album.cue").write_text("FILE album.flac WAVE\n")
    (music / "odd.ape").write_bytes(b"MAC ")
    (music / ".hidden").mkdir()
    put(music, ".hidden/x.flac")
    put(music, "@eaDir/thumb.flac")
    catalog, report = scan(music, home)
    assert [t["title"] for t in catalog["tracks"]] == ["Good"]
    assert report.skipped[folder.UNREADABLE] == 1 and report.skipped[folder.ONE_FILE_ALBUM] == 1
    assert report.other_types == {".ape": 1} and report.files == 3
    assert any("couldn't be read" in line for line in report.lines())


def test_a_few_stray_play_counts_are_left_out(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    p = put(music, "a.mp3", "blank.mp3")
    id3(p, TIT2(encoding=3, text="Counted"), TPE1(encoding=3, text="A"), PCNT(count=3))
    for i in range(3):
        tagged(music, f"b{i}.flac", TITLE=f"B{i}", ARTIST="B")
    catalog, report = scan(music, home)
    assert all("play_count" not in t for t in catalog["tracks"]) and report.play_counts_dropped == 1


def test_scan_command_reports_and_writes_the_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    music = tmp_path / "music"
    tagged(music, "a.flac", TITLE="Song", ARTIST="Band", DATE="1991", GENRE="Rock")
    put(music, "loose.flac")
    out = tmp_path / "catalog.json"
    assert main(["scan", str(music), "--catalog", str(out), "--name", "Records"]) == 0
    text = capsys.readouterr().out
    assert "Music files found: 2. Used: 1." in text and "loose.flac" in text and "year: 100%" in text
    catalog = json.loads(out.read_text(encoding="utf-8"))
    Draft202012Validator(SCHEMA).validate(catalog)
    assert catalog["source"]["library"] == "Records" and catalog["tracks"][0]["title"] == "Song"
    assert main(["scan", str(tmp_path / "nowhere")]) == 1


def test_a_file_that_failed_is_tried_again(tmp_path, monkeypatch):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "a.flac", TITLE="Song", ARTIST="A")
    real = tags.read
    monkeypatch.setattr(tags, "read", lambda path: (_ for _ in ()).throw(PermissionError("share dropped")))
    assert scan(music, home)[0]["tracks"] == []
    monkeypatch.setattr(tags, "read", real)
    assert [t["title"] for t in scan(music, home)[0]["tracks"]] == ["Song"]  # same file, read this time


def test_a_new_way_of_reading_reads_every_file_again(tmp_path, monkeypatch):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "a.flac", TITLE="Song", ARTIST="A")
    before = scan(music, home)[0]["tracks"][0]["id"]
    monkeypatch.setattr(folder, "READER", folder.READER + 1)
    reads = []
    real = tags.read
    monkeypatch.setattr(tags, "read", lambda path: reads.append(path) or real(path))
    assert scan(music, home)[0]["tracks"][0]["id"] == before and len(reads) == 1
    assert scan(music, home) and len(reads) == 1  # and then not again


def test_two_spellings_of_one_name_dont_stop_the_scan(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    nfc, nfd = unicodedata.normalize("NFC", "Jóga.flac"), unicodedata.normalize("NFD", "Jóga.flac")
    tagged(music, nfc, TITLE="One", ARTIST="Björk")
    if (music / nfd).exists():
        pytest.skip("this file system treats the two spellings as one name")
    tagged(music, nfd, TITLE="Two", ARTIST="Björk")
    catalog, report = scan(music, home)
    assert len(catalog["tracks"]) == 1 and report.skipped[folder.SAME_NAME] == 1


@pytest.mark.skipif(os.name == "nt", reason="making symlinks needs extra rights on Windows")
def test_linked_folders_are_followed_once(tmp_path):
    music, home, elsewhere = tmp_path / "music", tmp_path / "home", tmp_path / "nas"
    tagged(elsewhere, "Rips/a.flac", TITLE="Ripped", ARTIST="A")
    music.mkdir()
    (music / "Rips").symlink_to(elsewhere / "Rips", target_is_directory=True)
    (elsewhere / "Rips" / "loop").symlink_to(elsewhere / "Rips", target_is_directory=True)
    catalog, _ = scan(music, home)
    assert [t["title"] for t in catalog["tracks"]] == ["Ripped"]


def test_audiobooks_and_videos_are_not_music(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    f = MP4(put(music, "book.m4b", "blank.m4a"))
    f["©nam"], f["©ART"] = ["Chapter 1"], ["Narrator"]
    f.save()
    catalog, report = scan(music, home)
    assert catalog["tracks"] == [] and report.files == 0


def test_ids_follow_the_music_through_swaps_and_renumbering(tmp_path):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "01.flac", TITLE="X", ARTIST="A")
    tagged(music, "02.flac", TITLE="Y", ARTIST="A")
    first = {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]}
    # Renumbered: 01 -> 02 and 02 -> 03 (made in two steps, as a file manager would).
    (music / "02.flac").rename(music / "03.flac")
    (music / "01.flac").rename(music / "02.flac")
    assert {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]} == first
    # Swapped names.
    (music / "02.flac").rename(music / "tmp.flac")
    (music / "03.flac").rename(music / "02.flac")
    (music / "tmp.flac").rename(music / "03.flac")
    assert {t["title"]: t["id"] for t in scan(music, home)[0]["tracks"]} == first


def test_junk_play_counts_dont_make_a_file_unreadable(tmp_path):
    p = vorbis(put(tmp_path, "a.flac"), TITLE="T", FMPS_PLAYCOUNT="inf")
    assert "play_count" not in tags.read(p).fields


def test_folders_without_inode_numbers_are_all_scanned(tmp_path, monkeypatch):
    music, home = tmp_path / "music", tmp_path / "home"
    tagged(music, "a/b/c.flac", TITLE="Deep", ARTIST="A")
    real = folder._stat_dir

    class NoInode:
        def __init__(self, st):
            self.st_dev, self.st_ino = st.st_dev, 0

    monkeypatch.setattr(folder, "_stat_dir", lambda here: NoInode(real(here)))
    assert [t["title"] for t in scan(music, home)[0]["tracks"]] == ["Deep"]

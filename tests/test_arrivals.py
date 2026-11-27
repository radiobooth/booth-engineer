"""Radio Booth's own record of when tracks joined a library: a baseline, then only real arrivals."""

import json
from datetime import UTC, datetime

import pytest

from radiobooth import arrivals, history


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    return tmp_path / "cfg"


def catalog(ids, kind="plex", library="Music"):
    return {
        "protocol": "radiobooth/catalog@0",
        "source": {"kind": kind, "library": library},
        "tracks": [{"id": str(i), "title": f"Song {i}", "artist": "A", "duration_ms": 200_000} for i in ids],
    }


def day(d):
    return datetime(2026, 11, d, 12, tzinfo=UTC)


def joined(c):
    return {t["id"]: (t["joined_after"], t["joined_by"]) for t in c["tracks"] if "joined_by" in t}


def test_the_first_read_is_a_baseline_with_no_dates(cfg):
    c = arrivals.annotate(catalog(range(50)), when=day(1))
    assert c["history_since"].startswith("2026-11-01T") and joined(c) == {}
    assert (cfg / "library-seen.json").is_file()


def test_a_new_track_joined_between_two_reads():
    arrivals.annotate(catalog(range(50)), when=day(1))
    arrivals.annotate(catalog(range(50)), when=day(10))
    c = arrivals.annotate(catalog([*range(50), 77]), when=day(20))
    assert joined(c) == {"77": ("2026-11-10", "2026-11-20")}
    later = arrivals.annotate(catalog([*range(50), 77]), when=day(28))  # and keeps those dates
    assert joined(later) == {"77": ("2026-11-10", "2026-11-20")} and later["history_since"].startswith(
        "2026-11-01"
    )


def test_a_bulk_import_joins_the_baseline():
    arrivals.annotate(catalog(range(100)), when=day(1))
    c = arrivals.annotate(catalog(range(400)), when=day(5))  # a moved library or a new folder: 300 at once
    assert joined(c) == {}
    c = arrivals.annotate(catalog([*range(400), "new"]), when=day(9))
    assert joined(c) == {"new": ("2026-11-05", "2026-11-09")}


def test_a_look_without_a_fresh_read_notes_nothing():
    arrivals.annotate(catalog(range(5)), when=day(1))
    c = arrivals.annotate(catalog([*range(5), 9]), fresh=False, when=day(3))
    assert joined(c) == {} and c["history_since"]
    c = arrivals.annotate(catalog([*range(5), 9]), when=day(4))
    assert joined(c) == {"9": ("2026-11-01", "2026-11-04")}


def test_each_library_has_its_own_record():
    arrivals.annotate(catalog(range(5)), when=day(1))
    c = arrivals.annotate(catalog([1, 2, 99], kind="folder"), when=day(2))
    assert joined(c) == {}  # the folder's first read is its own baseline


def test_the_same_library_at_a_new_address_carries_on(cfg):
    arrivals.annotate(catalog(range(20)), where="http://192.168.1.5:32400", when=day(1))
    arrivals.annotate(catalog([*range(20), 50]), where="http://192.168.1.5:32400", when=day(3))
    c = arrivals.annotate(catalog([*range(20), 50, 51]), where="http://192.168.1.7:32400", when=day(6))
    assert joined(c) == {"50": ("2026-11-01", "2026-11-03"), "51": ("2026-11-03", "2026-11-06")}
    assert c["history_since"].startswith("2026-11-01")
    assert len(json.loads((cfg / "library-seen.json").read_text())["sources"]) == 1  # moved, not copied
    look = arrivals.annotate(catalog([*range(20), 50]), fresh=False, where="http://plex.local:32400")
    assert joined(look) == {"50": ("2026-11-01", "2026-11-03")}  # previews find it too


def test_songs_that_become_usable_are_no_arrivals():
    arrivals.annotate(catalog(range(5)), also=["5", "6"], when=day(1))  # 5 and 6 had no tags then
    c = arrivals.annotate(catalog(range(8)), when=day(4))
    assert joined(c) == {"7": ("2026-11-01", "2026-11-04")}


def test_lengths_either_side_of_a_step_are_the_same_song():
    arrivals.annotate(
        catalog([1]) | {"tracks": [{"id": "1", "title": "S", "artist": "A", "duration_ms": 182999}]},
        when=day(1),
    )
    c = arrivals.annotate(
        catalog([]) | {"tracks": [{"id": "1b", "title": "S", "artist": "A", "duration_ms": 183001}]},
        when=day(2),
    )
    assert joined(c) == {}


def test_another_folder_or_server_is_a_new_baseline():
    arrivals.annotate(catalog(range(5), kind="folder"), where="/music", when=day(1))
    c = arrivals.annotate(catalog(range(100, 150), kind="folder"), where="/other", when=day(2))
    assert joined(c) == {}
    c = arrivals.annotate(catalog([*range(5), 7], kind="folder"), where="/music", when=day(3))
    assert joined(c) == {"7": ("2026-11-01", "2026-11-03")}
    assert "/music" not in (arrivals.path()).read_text()  # no paths kept


def test_a_known_song_under_a_new_id_is_no_arrival():
    arrivals.annotate(catalog(range(5)), when=day(1))
    arrivals.annotate(catalog([*range(5), 9]), when=day(3))  # 9 really arrived
    moved = catalog([0, 1, 2, 3, 9])
    moved["tracks"][4]["id"] = "9b"  # Plex rescanned 9 and gave it a new id
    moved["tracks"].append(
        {"id": "4b", "title": "Song 4", "artist": "a ", "duration_ms": 200_400}
    )  # 4, moved
    c = arrivals.annotate(moved, when=day(8))
    assert joined(c) == {"9b": ("2026-11-01", "2026-11-03")}


@pytest.mark.parametrize(
    "text",
    ["", "junk", "[]", '{"sources": {"plex:Music": {"since": 1}}}', '{"sources": []}'],
)
def test_a_broken_file_starts_over(cfg, text):
    cfg.mkdir()
    (cfg / "library-seen.json").write_text(text)
    c = arrivals.annotate(catalog(range(3)), when=day(1))
    assert joined(c) == {} and c["history_since"].startswith("2026-11-01T")
    assert json.loads((cfg / "library-seen.json").read_text())["version"] == 1


def test_damaged_entries_are_left_out(cfg):
    arrivals.annotate(catalog(range(3)), when=day(1))
    data = json.loads((cfg / "library-seen.json").read_text())
    (rec,) = data["sources"].values()
    rec["tracks"] |= {"x": ["not", "a", "hash"]}
    rec["joined"] |= {"1": ["2026-W47-1", "2026-11-01"], "2": "2026-11-01", "0": ["2026-10-01", "2026-10-09"]}
    (cfg / "library-seen.json").write_text(json.dumps(data))
    c = arrivals.annotate(catalog(range(3)), when=day(2))
    assert joined(c) == {"0": ("2026-10-01", "2026-10-09")}


def test_file_trouble_sends_the_catalog_without_arrivals(monkeypatch):
    monkeypatch.setattr(
        arrivals.config, "write_atomically", lambda *a: (_ for _ in ()).throw(OSError("full"))
    )
    c = arrivals.annotate(catalog(range(3)))
    assert "history_since" not in c


def test_history_annotates_arrivals_too():
    history.annotate(catalog(range(3)))
    c = history.annotate(catalog([0, 1, 2, 3]))
    assert "joined_by" in c["tracks"][3] and "joined_by" not in c["tracks"][0]


def test_a_retagged_song_that_moves_later_is_still_known():
    arrivals.annotate(catalog(range(5)), when=day(1))
    retagged = catalog(range(5))
    retagged["tracks"][0]["artist"] = "Björk"  # same id, fixed tags
    assert joined(arrivals.annotate(retagged, when=day(2))) == {}
    moved = catalog(range(1, 5))
    moved["tracks"].append({"id": "0b", "title": "Song 0", "artist": "Björk", "duration_ms": 200_000})
    assert joined(arrivals.annotate(moved, when=day(3))) == {}


def test_ids_handed_out_again_carry_no_old_dates():
    old = [{"id": str(i), "title": f"Old {i}", "artist": "A", "duration_ms": 200_000} for i in range(300)]
    arrivals.annotate(catalog([]) | {"tracks": old}, when=day(1))
    arrivals.annotate(
        catalog([]) | {"tracks": [*old, {"id": "300", "title": "Arrived", "artist": "A", "duration_ms": 1}]},
        when=day(2),
    )
    # A new Plex database: the same songs under shuffled ids, so id 300 now holds an old song.
    reset = [
        {"id": str((i + 1) % 301), "title": f"Old {i}", "artist": "A", "duration_ms": 200_000}
        for i in range(300)
    ]
    reset.append({"id": "0", "title": "Arrived", "artist": "A", "duration_ms": 1})
    c = arrivals.annotate(catalog([]) | {"tracks": reset}, when=day(5))
    assert joined(c) == {"0": ("2026-11-01", "2026-11-02")}  # the dates follow the song, not the id

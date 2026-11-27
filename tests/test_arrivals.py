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
        "tracks": [{"id": str(i)} for i in ids],
    }


def day(d):
    return datetime(2026, 11, d, 12, tzinfo=UTC)


def joined(c):
    return {t["id"]: (t["joined_after"], t["joined_by"]) for t in c["tracks"] if "joined_by" in t}


def test_the_first_read_is_a_baseline_with_no_dates(cfg):
    c = arrivals.annotate(catalog(range(50)), when=day(1))
    assert c["history_since"] == "2026-11-01T12:00:00Z" and joined(c) == {}
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


@pytest.mark.parametrize("text", ["", "junk", "[]", '{"sources": {"plex:Music": {"since": 1}}}'])
def test_a_broken_file_starts_over(cfg, text):
    cfg.mkdir()
    (cfg / "library-seen.json").write_text(text)
    c = arrivals.annotate(catalog(range(3)), when=day(1))
    assert joined(c) == {} and c["history_since"] == "2026-11-01T12:00:00Z"
    assert json.loads((cfg / "library-seen.json").read_text())["version"] == 1


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

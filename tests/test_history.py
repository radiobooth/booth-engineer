import json
from datetime import UTC, datetime

import pytest
from test_deliver import make_show

from radiobooth import history
from radiobooth.cli import remember


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    return tmp_path / "cfg"


def catalog(*ids):
    return {"protocol": "radiobooth/catalog@0", "tracks": [{"id": i} for i in ids]}


def test_delivered_tracks_are_marked_in_later_catalogs(tmp_path, cfg):
    package = json.loads((make_show(tmp_path) / "show.json").read_text())
    history.record_package(package, datetime(2026, 11, 5, 8, 0, tzinfo=UTC))
    assert (cfg / "history.json").is_file()
    tracks = history.annotate(catalog("101", "103", "999"))["tracks"]
    shown = [{"at": "2026-11-05T08:00:00Z", "title": package["title"]}]
    assert tracks == [
        {"id": "101", "in_shows": 1, "last_in_show_at": "2026-11-05T08:00:00Z", "recent_shows": shown},
        {"id": "103", "in_shows": 1, "last_in_show_at": "2026-11-05T08:00:00Z", "recent_shows": shown},
        {"id": "999"},
    ]
    entry = history.load()["103"]["shows"][0]
    assert entry["show"] == package["show_id"] and entry["slot"] == 3


def test_shows_are_counted_newest_first_and_a_show_only_once():
    history.record(["1", "2"], datetime(2026, 11, 1, tzinfo=UTC), show="s1", title="Rain")
    history.record(["2"], datetime(2026, 11, 4, tzinfo=UTC), show="s2", title="Sun")
    history.record(["2"], datetime(2026, 11, 4, 1, tzinfo=UTC), show="s2", title="Sun")  # delivered again
    h = history.load()
    assert h["1"]["count"] == 1 and h["2"]["count"] == 2
    assert [s["title"] for s in h["2"]["shows"]] == ["Sun", "Rain"]
    for day in range(5, 20):
        history.record(["2"], datetime(2026, 11, day, tzinfo=UTC), show=f"d{day}")
    h = history.load()["2"]
    assert h["count"] == 17 and len(h["shows"]) == history.KEEP
    t = history.annotate(catalog("2"))["tracks"][0]
    assert t["in_shows"] == 17 and [s["at"][:10] for s in t["recent_shows"]] == [
        "2026-11-19",
        "2026-11-18",
        "2026-11-17",
    ]


def test_the_old_history_carries_over_as_a_floor(cfg):
    cfg.mkdir()
    (cfg / "history.json").write_text(json.dumps({"version": 1, "tracks": {"1": "2026-11-01T00:00:00Z"}}))
    t = history.annotate(catalog("1"))["tracks"][0]
    assert t == {
        "id": "1",
        "in_shows": 1,
        "in_shows_at_least": True,
        "last_in_show_at": "2026-11-01T00:00:00Z",
        "recent_shows": [{"at": "2026-11-01T00:00:00Z"}],
    }
    history.record(["1"], datetime(2026, 11, 9, tzinfo=UTC), show="s", title="T")
    t = history.annotate(catalog("1"))["tracks"][0]
    assert t["in_shows"] == 2 and t["in_shows_at_least"] and t["last_in_show_at"] == "2026-11-09T00:00:00Z"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"tracks": []}',
        '{"tracks": {"1": 5}}',
        '{"tracks": {"1": {"count": 1}}}',
        '{"tracks": {"1": {"count": 1, "shows": null}}}',
    ],
)
def test_a_broken_or_missing_history_is_empty(cfg, text):
    assert history.load() == {}
    cfg.mkdir()
    (cfg / "history.json").write_text(text)
    assert history.load() == {}
    assert history.annotate(catalog("1"), fresh=False)["tracks"] == [{"id": "1"}]
    history.record(["1"])  # and the next delivery starts it over
    assert list(history.load()) == ["1"]


def test_history_trouble_never_fails_a_delivery(tmp_path, monkeypatch):
    show = make_show(tmp_path)
    monkeypatch.setattr(history, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    log = []
    remember(show, log.append)
    assert "disk full" in log[0]


def test_each_person_sharing_booth_has_their_own_history(tmp_path, cfg):
    history.record(["101"], datetime(2026, 11, 5, tzinfo=UTC))
    history.record(["202"], datetime(2026, 11, 6, tzinfo=UTC), person="p_ab12")
    assert (cfg / "history-p_ab12.json").is_file()
    assert list(history.load()) == ["101"] and list(history.load("p_ab12")) == ["202"]
    assert [
        t.get("last_in_show_at") for t in history.annotate(catalog("101", "202"), "p_ab12")["tracks"]
    ] == [None, "2026-11-06T00:00:00Z"]


def test_damaged_shows_are_left_out(cfg):
    cfg.mkdir()
    shows = [{"at": "x", "title": "Bad"}, {"at": "2026-11-20T10:00:00Z", "title": ""}]
    (cfg / "history.json").write_text(
        json.dumps({"version": 2, "tracks": {"1": {"count": 2, "shows": shows}}})
    )
    t = history.annotate(catalog("1"), fresh=False)["tracks"][0]
    assert t["last_in_show_at"] == "2026-11-20T10:00:00Z" and t["recent_shows"] == [
        {"at": "2026-11-20T10:00:00Z"}
    ]

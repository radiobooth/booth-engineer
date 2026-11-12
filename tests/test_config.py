import json

from radiobooth import cli, config


def test_saved_address_follows_booth_dj_to_its_new_home(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    monkeypatch.setenv("BOOTH_CONFIG", str(p))
    p.write_text(json.dumps({"server": "https://booth-dj-juvsqx4frq-uc.a.run.app/", "device_token": "be_x"}))
    assert config.load() == {"server": cli.DEFAULT_SERVER, "device_token": "be_x"}


def test_other_saved_addresses_stay_put(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    monkeypatch.setenv("BOOTH_CONFIG", str(p))
    p.write_text(json.dumps({"server": "http://localhost:8080"}))
    assert config.load()["server"] == "http://localhost:8080"


def test_old_addresses_move_to_the_default():
    assert set(config.MOVED.values()) == {cli.DEFAULT_SERVER}


def test_plex_client_id_is_made_once(tmp_path, monkeypatch):
    from radiobooth import config

    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    first = config.plex_client_id()
    assert first.startswith("radiobooth-") and config.plex_client_id() == first
    assert config.load()["plex_client_id"] == first


def test_people_with_an_odd_plex_user_share_with_nobody(tmp_path, monkeypatch):
    from radiobooth import config

    settings = {
        "server": "https://booth.example",
        "people": [
            {"id": "p_a", "device_token": "a", "server": "https://booth.example", "plex_user": 3427736},
            {
                "id": "p_b",
                "device_token": "b",
                "server": "https://booth.example",
                "plex_user": {"id": 5, "title": "j"},
            },
        ],
    }
    assert [p["plex_user"] for p in config.people(settings)] == [None, {"id": 5, "title": "j"}]


def test_a_busy_config_file_is_read_again_on_windows(tmp_path, monkeypatch):
    """Windows refuses to read a file while another thread replaces it; Booth tries again for a moment."""
    import sys
    from pathlib import Path

    from radiobooth import config

    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    config.save({"name": "linus"})
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config.time, "sleep", lambda s: None)
    real, busy = Path.read_text, [2]

    def read_text(self, *a, **kw):
        if busy[0]:
            busy[0] -= 1
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert config.load()["name"] == "linus"

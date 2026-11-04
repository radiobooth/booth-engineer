"""Booth Engineer against a stand-in Booth DJ on localhost (tests only; the product never listens)."""

import gzip
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_deliver import make_show

from radiobooth import config
from radiobooth.cli import main
from radiobooth.link import Link, LinkError, Station, handle, pair, run


class FakeDJ:
    """Answers like Booth DJ and records what it was sent."""

    def __init__(self):
        self.calls, self.claims_until_paired, self.queue = [], 2, []
        self.catalogs, self.results, self.files = [], [], {}
        dj = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, data=None, raw=None):
                body = raw if raw is not None else json.dumps(data or {}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                return self.rfile.read(int(self.headers.get("Content-Length", 0)))

            def do_GET(self):
                dj.calls.append(("GET", self.path, self.headers.get("Authorization")))
                name = self.path.split("/files/", 1)[1].split("?")[0]
                self.reply(200, raw=dj.files[name])

            def do_POST(self):
                data = json.loads(self.body() or b"{}")
                dj.calls.append(("POST", self.path, self.headers.get("Authorization")))
                if self.path == "/v0/pair/start":
                    return self.reply(
                        200,
                        {
                            "code": "ABCD-2345",
                            "poll_token": "bp_x",
                            "expires_in": 600,
                            "pair_url": "http://dj.test/",
                        },
                    )
                if self.path == "/v0/pair/claim":
                    dj.claims_until_paired -= 1
                    if dj.claims_until_paired > 0:
                        return self.reply(202, {"status": "waiting"})
                    return self.reply(200, {"device_token": "be_secret"})
                if self.path == "/v0/checkin":
                    if self.headers.get("Authorization") != "Bearer be_secret":
                        return self.reply(401, {"error": "Unknown Booth Engineer"})
                    shows = dj.queue.pop(0) if dj.queue else []
                    return self.reply(200, {"next_checkin_s": 10, "shows": shows})
                if self.path.endswith("/result"):
                    dj.results.append((self.path.split("/")[3], data))
                    return self.reply(204, raw=b"")
                self.reply(404, {"error": "no"})

            def do_PUT(self):
                dj.calls.append(("PUT", self.path, self.headers.get("Authorization")))
                assert self.headers.get("Content-Encoding") == "gzip"
                dj.catalogs.append(json.loads(gzip.decompress(self.body())))
                self.reply(202, {"status": "making"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def dj():
    d = FakeDJ()
    yield d
    d.server.shutdown()


def test_pair_waits_for_the_phone(dj):
    shown = []
    token = pair(Link(dj.url), "linus", show=shown.append, sleep=lambda s: None)
    assert token == "be_secret" and shown[0]["code"] == "ABCD-2345"
    assert [c[1] for c in dj.calls] == ["/v0/pair/start", "/v0/pair/claim", "/v0/pair/claim"]


def test_pair_command_saves_private_config(dj, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setattr("radiobooth.link.time.sleep", lambda s: None)
    assert main(["pair", "--server", dj.url, "--name", "linus"]) == 0
    assert "ABCD-2345" in capsys.readouterr().out
    saved = config.load()
    assert saved == {"server": dj.url, "device_token": "be_secret", "name": "linus"}
    assert stat.S_IMODE(os.stat(config.path()).st_mode) == 0o600


def station(log, delivered=None, fail=None):
    def deliver(show_dir: Path) -> str:
        if fail:
            raise RuntimeError(fail)
        delivered.append(
            sorted(p.relative_to(show_dir).as_posix() for p in show_dir.rglob("*") if p.is_file())
        )
        return "Wipers On, Long Way Home"

    catalog = {"protocol": "radiobooth/catalog@0", "tracks": [{"id": "1"}]}
    return Station(catalog=lambda: catalog, deliver=deliver, log=log.append)


def serve_show(dj, tmp_path):
    show = make_show(tmp_path)
    for p in show.rglob("*"):
        if p.is_file():
            dj.files[p.relative_to(show).as_posix()] = p.read_bytes()
    return {name: f"{dj.url}/files/{name}?sig=1" for name in dj.files}


def test_run_sends_catalog_then_delivers_and_reports(dj, tmp_path):
    files = serve_show(dj, tmp_path)
    dj.queue = [
        [
            {
                "show_id": "show_1",
                "status": "queued",
                "action": "send_catalog",
                "catalog_url": "/v0/shows/show_1/catalog",
            }
        ],
        [{"show_id": "show_1", "status": "making"}],
        [{"show_id": "show_1", "status": "ready", "action": "deliver", "title": "Wipers", "files": files}],
    ]
    log, delivered = [], []
    link = Link(dj.url, "be_secret")
    for _ in range(3):
        run(link, station(log, delivered), once=True)
    assert dj.catalogs == [{"protocol": "radiobooth/catalog@0", "tracks": [{"id": "1"}]}]
    assert delivered == [["breaks/01.mp3", "breaks/02.mp3", "breaks/03.mp3", "show.json"]]
    assert dj.results == [("show_1", {"ok": True, "playlist": "Wipers On, Long Way Home"})]
    # Signed download URLs carry no token; API calls do.
    assert all(auth is None for m, path, auth in dj.calls if path.startswith("/files/"))
    assert all(auth == "Bearer be_secret" for m, path, auth in dj.calls if path.startswith("/v0/"))


def test_failed_delivery_is_reported(dj, tmp_path):
    files = serve_show(dj, tmp_path)
    log = []
    handle(
        Link(dj.url, "be_secret"),
        station(log, fail="Plex is asleep"),
        {"show_id": "show_2", "action": "deliver", "files": files},
    )
    assert dj.results == [("show_2", {"ok": False, "error": "Plex is asleep"})]


def test_package_names_cannot_escape_the_folder(tmp_path):
    with pytest.raises(LinkError, match="Refusing"):
        Link("http://dj.test").download({"../evil": "http://dj.test/x"}, tmp_path)


def test_run_backs_off_when_unreachable_and_stops_when_unpaired(dj):
    log, waits = [], []
    link = Link("http://127.0.0.1:9", "be_secret", timeout=2)  # nothing listens on port 9
    with pytest.raises(StopIteration):
        run(link, station(log), sleep=lambda s: waits.append(s) or (len(waits) < 3 or next(iter(()))))
    assert waits == [10.0, 20.0, 40.0]
    with pytest.raises(LinkError) as e:
        run(Link(dj.url, "be_wrong"), station(log), once=True)
    assert e.value.status == 401

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
from radiobooth.link import GENERIC_FAILURE, Link, LinkError, PackageError, Station, handle, run


class FakeDJ:
    """Answers like Booth DJ and records what it was sent."""

    def __init__(self):
        self.calls, self.queue, self.pairs = [], [], []
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
                if self.path == "/v0/pair":
                    dj.pairs.append(data)
                    if data.get("code") != "ABCD-2345":
                        return self.reply(404, {"error": "That code didn't work."})
                    return self.reply(200, {"device_token": "be_secret", "name": data["name"]})
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


def test_redeem_trades_the_code_for_a_token(dj):
    assert Link(dj.url).redeem("ABCD-2345", "linus") == "be_secret"
    assert dj.pairs == [{"code": "ABCD-2345", "name": "linus"}] and dj.calls[0][2] is None
    with pytest.raises(LinkError, match="didn't work") as exc:
        Link(dj.url).redeem("WXYZ-2345", "linus")
    assert exc.value.status == 404


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    (tmp_path / "cfg").mkdir()
    return tmp_path / "cfg"


def test_pair_command_saves_private_config(dj, cfg):
    (cfg / "config.tmp").write_text("old")  # a stale, readable temp file is ignored
    os.chmod(cfg / "config.tmp", 0o644)
    assert main(["pair", "ABCD-2345", "--server", dj.url, "--name", "linus"]) == 0
    saved = config.load()
    assert saved == {"server": dj.url, "device_token": "be_secret", "name": "linus"}
    if os.name == "posix":  # Windows has no mode bits; the file sits in the user's own profile folder
        assert stat.S_IMODE(os.stat(config.path()).st_mode) == 0o600
    assert sorted(p.name for p in cfg.iterdir()) == ["config.json", "config.tmp"]


def test_pair_command_asks_for_the_code(dj, cfg, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: " abcd-2345 ".upper())
    assert main(["pair", "--server", dj.url, "--name", "linus"]) == 0
    assert f"open {dj.url}/" in capsys.readouterr().err
    assert config.load()["device_token"] == "be_secret"


def test_pair_command_with_a_bad_or_missing_code(dj, cfg, monkeypatch, capsys):
    assert main(["pair", "WXYZ-2345", "--server", dj.url]) == 1
    assert "didn't work" in capsys.readouterr().err
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError))
    assert main(["pair", "--server", dj.url]) == 1
    assert "no code" in capsys.readouterr().err
    assert config.load() == {}


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
    # The details (which could name local paths or the Plex address) stay in the local log.
    assert dj.results == [("show_2", {"ok": False, "error": GENERIC_FAILURE})]
    assert any("Plex is asleep" in line for line in log)


def test_package_names_cannot_escape_the_folder(dj, tmp_path):
    with pytest.raises(PackageError, match="Refusing"):
        Link("https://dj.test").download({"../evil": "http://dj.test/x"}, tmp_path)
    # In a check-in it counts as a failed delivery, reported once, and the next show still runs.
    log, delivered = [], []
    dj.queue = [
        [
            {"show_id": "bad", "action": "deliver", "files": {"../evil": f"{dj.url}/files/x"}},
            {"show_id": "next", "action": "send_catalog", "catalog_url": "/v0/shows/next/catalog"},
        ]
    ]
    run(Link(dj.url, "be_secret"), station(log, delivered), once=True)
    assert dj.results == [("bad", {"ok": False, "error": GENERIC_FAILURE})] and len(dj.catalogs) == 1


def test_lost_report_is_retried_without_delivering_again(dj, tmp_path, monkeypatch):
    files = serve_show(dj, tmp_path)
    item = {"show_id": "show_3", "status": "ready", "action": "deliver", "title": "W", "files": files}
    dj.queue = [[item], [item]]
    log, delivered = [], []
    st, link = station(log, delivered), Link(dj.url, "be_secret")
    real = link.report
    monkeypatch.setattr(link, "report", lambda *a, **k: (_ for _ in ()).throw(LinkError("network down")))
    run(link, st, once=True)
    assert delivered and st.unreported == {"show_3": {"playlist": "Wipers On, Long Way Home"}}
    monkeypatch.setattr(link, "report", real)
    run(link, st, once=True)
    assert len(delivered) == 1 and st.unreported == {}
    assert dj.results == [("show_3", {"ok": True, "playlist": "Wipers On, Long Way Home"})]


def test_truncated_response_backs_off(monkeypatch):
    import http.client

    def boom(*a, **k):
        raise http.client.IncompleteRead(b"{", 10)

    monkeypatch.setattr("radiobooth.link._api.open", boom)
    with pytest.raises(LinkError, match="Could not reach"):
        Link("https://dj.test", "t").checkin()


@pytest.mark.parametrize("url", ["http://evil.test/collect", "//evil.test/collect", "evil"])
def test_token_and_catalog_only_go_to_the_paired_server(url, monkeypatch):
    monkeypatch.setattr("radiobooth.link._api.open", lambda *a, **k: pytest.fail("sent somewhere"))
    with pytest.raises(LinkError, match="Refusing"):
        Link("https://dj.test", "be_secret").send_catalog(url, {"tracks": []})


def test_api_calls_do_not_follow_redirects(dj):
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.send_response(307)
            self.send_header("Location", f"{dj.url}/v0/checkin")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(LinkError) as e:
            Link(f"http://127.0.0.1:{srv.server_port}", "be_secret").checkin()
        assert e.value.status == 307 and not [c for c in dj.calls if c[1] == "/v0/checkin"]
    finally:
        srv.shutdown()


@pytest.mark.parametrize("body", [b'{"next_checkin_s": 1', b"[1, 2]"])
def test_malformed_replies_are_retryable(body, monkeypatch):
    import io

    class Resp(io.BytesIO):
        status = 200

    monkeypatch.setattr("radiobooth.link._api.open", lambda *a, **k: Resp(body))
    with pytest.raises(LinkError):
        Link("https://dj.test", "t").checkin()


def test_short_download_is_retryable(dj, tmp_path):
    class Short(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"only ten b")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Short)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(LinkError):
            Link(dj.url).download({"show.json": f"http://127.0.0.1:{srv.server_port}/x"}, tmp_path)
    finally:
        srv.shutdown()


def test_run_explains_how_to_fix_an_unknown_engineer(dj, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    config.save({"server": dj.url, "device_token": "be_wrong"})
    for k, v in {"PLEX_URL": "http://plex", "PLEX_TOKEN": "t", "BOOTH_BREAKS_LIBRARY": "RB"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("BOOTH_BREAKS_DIR", str(tmp_path))
    assert main(["run", "--once"]) == 1
    assert "booth pair" in capsys.readouterr().err


def test_run_backs_off_when_unreachable_and_stops_when_unpaired(dj):
    log, waits = [], []
    link = Link("http://127.0.0.1:9", "be_secret", timeout=2)  # nothing listens on port 9
    with pytest.raises(StopIteration):
        run(link, station(log), sleep=lambda s: waits.append(s) or (len(waits) < 3 or next(iter(()))))
    assert waits == [10.0, 20.0, 40.0]
    with pytest.raises(LinkError) as e:
        run(Link(dj.url, "be_wrong"), station(log), once=True)
    assert e.value.status == 401


@pytest.mark.parametrize("body", [b"[]", b'{"error": 5}', b"not json", "truncated"])
def test_odd_error_bodies_keep_the_status(body, monkeypatch):
    import http.client
    import io
    import urllib.error

    class Body(io.BytesIO):
        def read(self, *a):
            if body == "truncated":
                raise http.client.IncompleteRead(b"{")
            return super().read(*a)

    def fail(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 503, "busy", {}, Body(b"" if body == "truncated" else body)
        )

    monkeypatch.setattr("radiobooth.link._api.open", fail)
    with pytest.raises(LinkError) as e:
        Link("https://dj.test", "t").checkin()
    assert e.value.status == 503 and "HTTP 503" in str(e.value)


@pytest.mark.parametrize("server", ["http://dj.example.com", "ftp://dj.test", "dj.test", "https://"])
def test_token_only_travels_over_https(server):
    with pytest.raises(LinkError):
        Link(server, "be_secret")


@pytest.mark.parametrize("server", ["https://dj.test", "http://localhost:8080", "http://127.0.0.1:8080"])
def test_https_or_this_machine_is_fine(server):
    Link(server, "be_secret")


@pytest.mark.parametrize(
    "reply", [{"shows": "nope"}, {"shows": [1]}, {"shows": [{"action": "deliver"}]}, {"shows": {"a": 1}}]
)
def test_odd_checkin_replies_are_retryable(reply, monkeypatch):
    monkeypatch.setattr(Link, "post", lambda self, path, data: (200, reply))
    log = []
    run(Link("https://dj.test", "t"), station(log), once=True)
    assert "doesn't understand" in log[-1] and "trying again" in log[-1]


@pytest.mark.parametrize(
    "wait,expect", [("soon", 60), (None, 60), (0, 5), (10**9, 3600), (True, 60), (30, 30)]
)
def test_checkin_wait_is_sane(wait, expect, monkeypatch):
    monkeypatch.setattr(Link, "post", lambda self, path, data: (200, {"next_checkin_s": wait}))
    assert Link("https://dj.test", "t").checkin()["next_checkin_s"] == expect


@pytest.mark.parametrize("url", ["http://storage.example.com/show.json", "file:///etc/passwd", None])
def test_package_downloads_need_https(url, dj, tmp_path):
    with pytest.raises(PackageError, match="insecure"):
        Link(dj.url).download({"show.json": url}, tmp_path)


def test_local_disk_trouble_fails_the_delivery_not_the_checkin(dj, tmp_path, monkeypatch):
    files = serve_show(dj, tmp_path / "src")
    dj.queue = [
        [
            {"show_id": "full", "action": "deliver", "files": files},
            {"show_id": "next", "action": "send_catalog", "catalog_url": "/v0/shows/next/catalog"},
        ]
    ]
    real_open = Path.open

    def full_disk(self, mode="r", *a, **k):
        if "w" in mode and "booth-show-" in str(self):
            raise OSError(28, "No space left on device")
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", full_disk)
    log = []
    run(Link(dj.url, "be_secret"), station(log, []), once=True)
    assert dj.results == [("full", {"ok": False, "error": GENERIC_FAILURE})] and len(dj.catalogs) == 1
    assert any("No space left" in line for line in log)


def test_music_library_comes_from_the_environment(monkeypatch):
    from radiobooth.cli import build_parser

    monkeypatch.setenv("BOOTH_MUSIC_LIBRARY", "Music")
    assert build_parser().parse_args(["run"]).library == "Music"
    assert build_parser().parse_args(["index"]).library == "Music"
    assert build_parser().parse_args(["run", "--library", "Other"]).library == "Other"
    monkeypatch.delenv("BOOTH_MUSIC_LIBRARY")
    assert build_parser().parse_args(["run"]).library is None

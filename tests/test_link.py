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
from radiobooth.link import (
    CATALOG_FAILURE,
    FILE_FAILURE,
    GENERIC_FAILURE,
    NO_SONGS_FAILURE,
    Link,
    LinkError,
    PackageError,
    Station,
    handle,
    run,
    run_all,
    send_file,
    sending,
)

SONG = {"id": "1", "title": "Song", "artist": "Band", "duration_ms": 200000}


class FakeDJ:
    """Answers like Booth DJ and records what it was sent."""

    def __init__(self):
        self.calls, self.queue, self.pairs = [], [], []
        self.catalogs, self.results, self.files = [], [], {}
        self.file_calls, self.uploads, self.file_replies = [], {}, {}
        self.catalog_reply = (202, {"status": "making"})
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
                if "/file/" in self.path:
                    step = self.path.rsplit("/", 1)[1]
                    show_id = self.path.split("/")[3]
                    dj.file_calls.append((show_id, step, data, self.headers.get("Authorization")))
                    status, reply = dj.file_replies.get(step, (200, None))
                    if step == "upload" and reply is None:
                        reply = {
                            "url": f"{dj.url}/upload/{show_id}?sig=1",
                            "headers": {"Content-Type": "audio/mpeg"},
                        }
                    return self.reply(status, reply) if reply is not None else self.reply(204, raw=b"")
                if self.path.endswith("/result"):
                    dj.results.append((self.path.split("/")[3], data))
                    return self.reply(204, raw=b"")
                self.reply(404, {"error": "no"})

            def do_PUT(self):
                dj.calls.append(("PUT", self.path, self.headers.get("Authorization")))
                if self.path.startswith("/busy/"):
                    self.body()
                    return self.reply(503, raw=b"<Error>SlowDown</Error>")
                if self.path.startswith("/refuse/"):
                    self.body()
                    return self.reply(403, raw=b"<Error>SignatureDoesNotMatch</Error>")
                if self.path.startswith("/upload/"):
                    dj.uploads[self.path.split("/")[2].split("?")[0]] = (self.body(), dict(self.headers))
                    return self.reply(200, raw=b"")
                assert self.headers.get("Content-Encoding") == "gzip"
                dj.catalogs.append(json.loads(gzip.decompress(self.body())))
                self.reply(*dj.catalog_reply)

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


TRACK = {"id": "1", "title": "Wipers", "artist": "Hüsker Dü", "duration_ms": 1000}


def station(log, delivered=None, fail=None):
    def deliver(show_dir: Path) -> str:
        if fail:
            raise RuntimeError(fail)
        delivered.append(
            sorted(p.relative_to(show_dir).as_posix() for p in show_dir.rglob("*") if p.is_file())
        )
        return "Wipers On, Long Way Home"

    catalog = {"protocol": "radiobooth/catalog@0", "tracks": [TRACK, {"id": "2"}]}
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
    # A track the catalog can't hold is left out, and the local log says so.
    assert dj.catalogs == [{"protocol": "radiobooth/catalog@0", "tracks": [TRACK]}]
    assert any("left out 1 tracks" in line and "no title" in line for line in log)
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
    from radiobooth.cli import NEEDS_PAIRING

    assert main(["run", "--once"]) == NEEDS_PAIRING
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


def test_a_problem_that_repeats_every_checkin_is_logged_once(dj):
    ask = {
        "show_id": "show_1",
        "status": "queued",
        "action": "send_catalog",
        "catalog_url": "/v0/shows/show_1/catalog",
    }
    dj.queue = [[ask], [ask], [ask], [ask]]
    log, tries = [], []

    def catalog():
        tries.append(1)
        if len(tries) < 3:
            raise RuntimeError("Plex no longer accepts Booth's sign-in")
        return {"protocol": "radiobooth/catalog@0", "tracks": [SONG]}

    st = Station(catalog=catalog, deliver=lambda p: "x", log=log.append)
    link = Link(dj.url, "be_secret")
    for _ in range(3):
        run(link, st, once=True)
    assert len(tries) == 3  # still tried at every check-in
    assert log == [
        "show_1: reading the library for a new show...",
        "show_1: Plex no longer accepts Booth's sign-in (Booth keeps trying; this is logged once)",
        "show_1: sent 1 tracks; the DJ is on it.",
    ]
    assert st.problems == {} and len(dj.catalogs) == 1


class Unreadable(Exception):
    lasting = True


def test_a_lasting_catalog_problem_fails_the_show_so_the_next_can_go(dj):
    ask = {
        "show_id": "show_1",
        "status": "queued",
        "action": "send_catalog",
        "catalog_url": "/v0/shows/show_1/catalog",
    }
    dj.queue = [[ask]] * 4
    log = []

    def catalog():
        raise Unreadable("Plex sent a reply Booth couldn't read.")

    st = Station(catalog=catalog, deliver=lambda p: "x", log=log.append)
    link = Link(dj.url, "be_secret")
    for _ in range(2):
        run(link, st, once=True)
    assert dj.results == [] and st.lasting == {"show_1": 2}  # a hiccup gets a few tries first
    run(link, st, once=True)
    assert dj.results == [("show_1", {"ok": False, "error": CATALOG_FAILURE})]
    assert st.lasting == {} and st.problems == {}
    assert log[-1].startswith("show_1: Plex sent a reply Booth couldn't read. Booth stopped trying")


def test_a_library_with_no_usable_songs_fails_the_show_with_a_plain_reason(dj):
    ask = {
        "show_id": "show_1",
        "status": "queued",
        "action": "send_catalog",
        "catalog_url": "/v0/shows/show_1/catalog",
    }
    dj.queue = [[ask]] * 3
    log = []
    no_artist = {"id": "2", "title": "Song", "duration_ms": 1000}
    st = Station(
        catalog=lambda: {"protocol": "radiobooth/catalog@0", "tracks": [no_artist]},
        deliver=lambda p: "x",
        log=log.append,
    )
    link = Link(dj.url, "be_secret")
    for _ in range(3):
        run(link, st, once=True)
    assert dj.catalogs == []  # never sent: Booth DJ would only refuse it
    assert dj.results == [("show_1", {"ok": False, "error": NO_SONGS_FAILURE})]
    why = "no songs it can use in your music library (1 left out; the first: track 0: no artist)"
    assert any(why in line for line in log)


def test_a_catalog_booth_dj_refuses_fails_the_show_without_backing_off(dj):
    ask = {
        "show_id": "show_1",
        "status": "queued",
        "action": "send_catalog",
        "catalog_url": "/v0/shows/show_1/catalog",
    }
    dj.queue = [[ask]] * 3
    dj.catalog_reply = (400, {"error": "Not a radiobooth/catalog@0 document: the catalog has no tracks"})
    log = []
    st = Station(
        catalog=lambda: {"protocol": "radiobooth/catalog@0", "tracks": [SONG]},
        deliver=lambda p: "x",
        log=log.append,
    )
    link = Link(dj.url, "be_secret")
    for _ in range(3):
        run(link, st, once=True)
    assert len(dj.catalogs) == 3
    assert dj.results == [("show_1", {"ok": False, "error": CATALOG_FAILURE})]
    assert not any("trying again in" in line for line in log)  # not mistaken for network trouble
    assert any("Booth DJ refused this library" in line for line in log)


def test_a_passing_catalog_problem_is_never_given_up_on(dj):
    ask = {
        "show_id": "show_1",
        "status": "queued",
        "action": "send_catalog",
        "catalog_url": "/v0/shows/show_1/catalog",
    }
    dj.queue = [[ask]] * 5

    def catalog():
        raise RuntimeError("Could not reach Plex")  # Plex restarting, say: it comes back

    st = Station(catalog=catalog, deliver=lambda p: "x", log=lambda m: None)
    for _ in range(5):
        run(Link(dj.url, "be_secret"), st, once=True)
    assert dj.results == []


def test_run_picks_up_a_plex_sign_in_saved_while_it_runs(dj, tmp_path, monkeypatch, capsys):
    from radiobooth.sources import plex as plex_source

    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR", "BOOTH_MUSIC_LIBRARY"):
        monkeypatch.delenv(k, raising=False)
    settings = {
        "server": dj.url,
        "device_token": "be_secret",
        "plex_url": "http://plex:32400",
        "plex_token": "old",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path),
    }
    config.save(settings)
    seen = []

    def build_catalog(client, library, exclude=None):
        seen.append(client.token)
        if client.token == "old":
            config.save(settings | {"plex_token": "new"})  # setup, run again in another window
            raise plex_source.PlexAuthError()
        return {"protocol": "radiobooth/catalog@0", "tracks": [SONG]}, 0

    monkeypatch.setattr(plex_source, "build_catalog", build_catalog)
    dj.queue = [
        [{"show_id": "s", "status": "queued", "action": "send_catalog", "catalog_url": "/v0/shows/s/catalog"}]
    ]
    assert main(["run", "--once"]) == 0
    assert seen == ["old", "new"] and len(dj.catalogs) == 1
    assert "using the one saved by setup" in capsys.readouterr().err


def test_a_refused_plex_token_from_the_shell_gives_way_to_setups(dj, tmp_path, monkeypatch, capsys):
    from radiobooth.sources import plex as plex_source

    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("PLEX_URL", "http://plex:32400")
    monkeypatch.setenv("PLEX_TOKEN", "exported-long-ago")
    for k in ("BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR", "BOOTH_MUSIC_LIBRARY"):
        monkeypatch.delenv(k, raising=False)
    config.save(
        {
            "server": dj.url,
            "device_token": "be_secret",
            "plex_url": "http://plex:32400",
            "plex_token": "fresh",
            "breaks_library": "Radio Booth",
            "breaks_dir": str(tmp_path),
        }
    )
    seen = []

    def build_catalog(client, library, exclude=None):
        seen.append(client.token)
        if client.token != "fresh":
            raise plex_source.PlexAuthError()
        return {"protocol": "radiobooth/catalog@0", "tracks": [SONG]}, 0

    monkeypatch.setattr(plex_source, "build_catalog", build_catalog)
    ask = {"show_id": "s", "status": "queued", "action": "send_catalog", "catalog_url": "/v0/shows/s/catalog"}
    dj.queue = [[ask]]
    assert main(["run", "--once"]) == 0
    assert seen == ["exported-long-ago", "fresh"] and len(dj.catalogs) == 1


def test_a_refused_plex_token_from_the_shell_says_to_unset_it(dj, tmp_path, monkeypatch, capsys):
    from radiobooth.sources import plex as plex_source

    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    for k, v in {"PLEX_URL": "http://plex", "PLEX_TOKEN": "dead", "BOOTH_BREAKS_LIBRARY": "RB"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("BOOTH_BREAKS_DIR", str(tmp_path))
    config.save({"server": dj.url, "device_token": "be_secret"})

    def build_catalog(client, library, exclude=None):
        raise plex_source.PlexAuthError()

    monkeypatch.setattr(plex_source, "build_catalog", build_catalog)
    ask = {"show_id": "s", "status": "queued", "action": "send_catalog", "catalog_url": "/v0/shows/s/catalog"}
    dj.queue = [[ask]]
    assert main(["run", "--once"]) == 0
    err = capsys.readouterr().err
    assert "Sign in to Plex again" in err and "PLEX_TOKEN is set here" in err


class ScriptedLink:
    """A Link whose check-ins answer from a script: a wait in seconds, or an exception to raise."""

    def __init__(self, name, answers, seen):
        self.name, self.answers, self.seen = name, list(answers), seen

    def checkin(self):
        self.seen.append(self.name)
        answer = self.answers.pop(0) if self.answers else StopIteration()
        if isinstance(answer, BaseException):
            raise answer
        return {"shows": [], "next_checkin_s": answer}


def test_people_sharing_booth_each_check_in_when_asked(monkeypatch):
    log, seen, waits, dropped = [], [], [], []
    own = ScriptedLink("own", [60, 60, 60], seen)
    theirs = ScriptedLink(
        "theirs", [10, 10, 10, 10, 10, LinkError("Booth DJ: Unknown Booth Engineer", 401)], seen
    )
    with pytest.raises(StopIteration):
        run_all([(own, station(log)), (theirs, station(log))], sleep=waits.append, unpaired=dropped.append)
    # Each as often as its Booth DJ asks; when one account forgets this computer, the other carries on.
    assert seen == ["own", *["theirs"] * 6, "own", "own", "own"]
    assert dropped == [1]
    assert waits == [10] * 6 + [60, 60]


def test_a_forgotten_own_account_stops_everything():
    seen = []
    own = ScriptedLink("own", [LinkError("Booth DJ: Unknown Booth Engineer", 401)], seen)
    theirs = ScriptedLink("theirs", [10], seen)
    with pytest.raises(LinkError):
        run_all([(own, station([])), (theirs, station([]))], sleep=lambda s: None, unpaired=lambda i: None)
    assert seen == ["own"]


# A show as one file, for the listener's phone


def file_station(log, made=None, fail=None, busy=None, scratch=None):
    """A station whose one file is a copy of `made`, put where it's asked to be (the hidden folder)."""
    seen = []

    def one_file(show_id, title, into):
        if fail:
            raise fail
        into.mkdir(parents=True, exist_ok=True)
        out = into / made.name
        out.write_bytes(made.read_bytes())
        seen.append(out)
        return out

    st = Station(
        catalog=lambda: {},
        deliver=lambda d: "",
        log=log.append,
        one_file=one_file,
        busy=busy,
        scratch=(lambda: scratch) if scratch else None,
    )
    st.seen = seen
    return st


def send(dj, station_, item=None):
    item = item or {"show_id": "show_f", "status": "delivered", "action": "send_file", "title": "Wipers"}
    thread = handle(Link(dj.url, "be_secret"), station_, item)
    from radiobooth import link as link_module

    running = link_module._sending.get(item["show_id"])
    if running:
        running.join(10)
    return thread


def test_a_show_goes_to_the_phone_as_one_file(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3" + b"x" * 5000)
    log, marks = [], []
    send(dj, file_station(log, made, busy=marks.append))
    steps = [(show, step, data) for show, step, data, _ in dj.file_calls]
    assert steps == [
        ("show_f", "making", {}),
        ("show_f", "upload", {"bytes": 5003}),
        ("show_f", "result", {"ok": True}),
    ]
    body, headers = dj.uploads["show_f"]
    assert body == made.read_bytes() and headers["Content-Type"] == "audio/mpeg"
    # The signed upload link carries no token; the API calls do.
    assert "Authorization" not in headers
    assert all(auth == "Bearer be_secret" for *_, auth in dj.file_calls)
    assert marks == [True, False]
    assert any("on its way to your phone" in line for line in log)


def test_a_file_that_cant_be_made_is_reported_without_details(dj):
    log = []
    send(dj, file_station(log, fail=OSError("C:/Users/me/Booth shows is full")))
    (show, step, data, _), *_ = dj.file_calls[1:]
    assert step == "result" and data == {"ok": False, "error": FILE_FAILURE}
    assert any("is full" in line for line in log)  # the reason stays here
    assert dj.uploads == {}


def test_a_file_nobody_wants_any_more_stops_quietly(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["making"] = (409, {"error": "Nobody is waiting"})
    log = []
    send(dj, file_station(log, made))
    assert [step for _, step, *_ in dj.file_calls] == ["making"]
    assert any("isn't wanted any more" in line for line in log)


def test_an_upload_link_must_be_https(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["upload"] = (200, {"url": "http://storage.example/x?sig=1"})
    log = []
    send(dj, file_station(log, made))
    assert [step for _, step, *_ in dj.file_calls] == ["making", "upload", "result"]
    assert dj.file_calls[-1][2] == {"ok": False, "error": FILE_FAILURE} and dj.uploads == {}


def test_a_file_already_on_its_way_isnt_sent_twice(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    gate = threading.Event()

    def slow(show_id, title, into):
        gate.wait(10)
        return made

    log = []
    st = Station(catalog=lambda: {}, deliver=lambda d: "", log=log.append, one_file=slow)
    link = Link(dj.url, "be_secret")
    item = {"show_id": "show_twice", "action": "send_file", "title": "x"}
    first = send_file(link, st, item)
    assert first is not None and sending()
    assert send_file(link, st, item) is None  # the next check-in asks again: it's under way
    gate.set()
    first.join(10)
    assert not sending()
    assert [step for _, step, *_ in dj.file_calls].count("making") == 1


def test_a_machine_that_cant_make_files_ignores_the_ask(dj):
    st = Station(catalog=lambda: {}, deliver=lambda d: "", log=lambda m: None)
    assert send_file(Link(dj.url, "be_secret"), st, {"show_id": "show_x", "action": "send_file"}) is None
    assert dj.file_calls == []


def test_storage_refusing_the_upload_fails_the_file_once(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["upload"] = (200, {"url": f"{dj.url}/refuse/show_f?sig=1"})
    log = []
    send(dj, file_station(log, made))
    assert [step for _, step, *_ in dj.file_calls] == ["making", "upload", "result"]
    assert dj.file_calls[-1][2] == {"ok": False, "error": FILE_FAILURE}
    assert any("HTTP 403" in line for line in log)


def test_upload_headers_are_read_whatever_their_case(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["upload"] = (
        200,
        {"url": f"{dj.url}/upload/show_f?sig=1", "headers": {"content-type": "audio/mpeg"}},
    )
    send(dj, file_station([], made))
    assert dj.uploads["show_f"][1]["Content-Type"] == "audio/mpeg"
    assert dj.file_calls[-1][2] == {"ok": True}


def test_the_file_is_held_while_it_uploads(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    lock = threading.Lock()
    held = []

    def one_file(show_id, title, into):
        held.append(lock.locked())
        return made

    st = Station(catalog=lambda: {}, deliver=lambda d: "", log=lambda m: None, one_file=one_file, mixing=lock)
    send(dj, st)
    assert held == [True] and not lock.locked() and dj.file_calls[-1][2] == {"ok": True}


def test_the_file_sent_is_a_private_copy_deleted_after(dj, tmp_path):
    made = tmp_path / "Copies" / "Wipers.mp3"
    made.parent.mkdir()
    made.write_bytes(b"ID3")
    st = file_station([], made, scratch=made.parent)
    send(dj, st)
    (sent,) = st.seen
    assert sent.parent == made.parent / ".phone-show_f" and dj.file_calls[-1][2] == {"ok": True}
    assert not sent.parent.exists() and made.exists()  # the page's own stays
    # Whatever happens, the private copy goes.
    dj.file_replies["upload"] = (409, {"error": "Nobody is waiting"})
    send(dj, st)
    assert not (made.parent / ".phone-show_f").exists()


def test_storage_trouble_is_retried_not_failed(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["upload"] = (200, {"url": f"{dj.url}/busy/show_f?sig=1"})
    log = []
    send(dj, file_station(log, made))
    assert [step for _, step, *_ in dj.file_calls] == ["making", "upload"]  # no result: tried again later
    assert any("HTTP 503" in line and "tries again" in line for line in log)


def test_booth_dj_refusing_a_step_fails_the_file_instead_of_retrying(dj, tmp_path):
    made = tmp_path / "Wipers.mp3"
    made.write_bytes(b"ID3")
    dj.file_replies["upload"] = (400, {"error": "bytes must be the file's size"})
    log = []
    send(dj, file_station(log, made))
    assert [step for _, step, *_ in dj.file_calls] == ["making", "upload", "result"]
    assert dj.file_calls[-1][2] == {"ok": False, "error": FILE_FAILURE}

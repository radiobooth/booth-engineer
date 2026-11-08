import http.client
import json
import threading
import time

import pytest
from test_setup import SERVER, FakePlex

from radiobooth import autostart, config, engine, onboard, update, web, websetup
from radiobooth.link import LinkError


def wait_for(check, timeout=5):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


@pytest.fixture
def booth(tmp_path, monkeypatch):
    """Booth's page on a free port, as the app serves it."""
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("BOOTH_SERVER", raising=False)
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR", "BOOTH_MUSIC_LIBRARY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(autostart, "installed", lambda platform=None, home=None: False)
    app = web.App("Den PC", platform="linux")
    key = web.page_key()
    httpd, link = web.serve(app, web.bind(0), key)
    port = httpd.server_address[1]
    yield app, port, key, link
    app.engine.stop()
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), data


def page_headers(port, key):
    return {
        "Cookie": f"{web.COOKIE}={key}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }


def act(port, key, action, body=None):
    status, _, data = call(port, "POST", f"/api/{action}", json.dumps(body or {}), page_headers(port, key))
    return status, json.loads(data)


def test_the_link_the_app_opens_lets_the_browser_in(booth):
    app, port, key, link = booth
    assert link == f"http://127.0.0.1:{port}/?k={key}"
    status, headers, _ = call(port, "GET", f"/?k={key}")
    assert status == 303 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert cookie.startswith(f"{web.COOKIE}={key};") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    status, headers, body = call(port, "GET", "/", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 200 and b"Radio Booth" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    status, _, body = call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 200 and json.loads(body)["engine"]["state"] == engine.NOT_SET_UP


def test_without_the_key_nothing_is_shown(booth):
    app, port, key, _ = booth
    assert call(port, "GET", "/?k=guess")[0] == 403
    status, _, body = call(port, "GET", "/api/state")
    assert status == 403 and b'"engine"' not in body and b"Open Booth from your computer" in body
    assert call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}=guess"})[0] == 403


def test_another_name_for_this_computer_is_refused(booth):
    # DNS rebinding: a website's own name pointed at 127.0.0.1 arrives with that name as Host.
    app, port, key, _ = booth
    cookie = {"Cookie": f"{web.COOKIE}={key}"}
    assert call(port, "GET", "/api/state", headers={**cookie, "Host": f"evil.example:{port}"})[0] == 421
    assert call(port, "GET", "/ping", headers={"Host": "evil.example"})[0] == 421


def test_changes_only_come_from_booths_own_page(booth):
    app, port, key, _ = booth
    good = page_headers(port, key)
    for bad in (
        {**good, "Origin": "https://evil.example"},
        {k: v for k, v in good.items() if k != "Origin"},
        {**good, "Cookie": ""},
    ):
        assert call(port, "POST", "/api/quit", "{}", bad)[0] == 403
    assert call(port, "POST", "/api/quit", "{}", {**good, "Content-Type": "text/plain"})[0] == 400
    assert not app.quit.is_set()
    assert act(port, key, "quit") == (200, {})
    wait_for(app.quit.is_set)


def test_the_page_answers_with_plain_words(booth):
    app, port, key, _ = booth
    status, data = act(port, key, "pair", {"code": ""})
    assert status == 422 and data["error"] == "Type the code from your phone first."
    assert act(port, key, "no-such-button")[0] == 422


def test_a_second_copy_finds_the_page(booth, monkeypatch):
    app, port, key, link = booth
    web.write_page_file(link)
    assert web.page_link() == link and web.answering(link)
    opened = []
    assert web.open_running(opened.append, wait_s=0) and opened == [link]


def test_the_page_key_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    key = web.page_key()
    assert len(key) > 40 and web.page_key() == key  # a page left open finds Booth again after a restart


@pytest.fixture
def plex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(onboard, "breaks_dir_candidates", lambda: [tmp_path / "Radio Booth"])
    monkeypatch.setattr(
        onboard, "start_sign_in", lambda cid: ({"id": 1, "code": "c"}, "https://app.plex.tv/x")
    )
    signed = threading.Event()

    def wait_sign_in(cid, pin, cancelled=None):
        signed.wait(5)
        return "acct-token"

    monkeypatch.setattr(onboard, "wait_sign_in", wait_sign_in)
    monkeypatch.setattr(onboard, "owned_servers", lambda token, cid: [SERVER, {**SERVER, "name": "Attic"}])
    monkeypatch.setattr(onboard, "reach", lambda server, token: (onboard.LOCAL_PLEX, True))
    monkeypatch.setattr(onboard, "plex_user_id", lambda: None)
    plex = FakePlex([{"title": "Music", "type": "artist"}, {"title": "Audiobooks", "type": "artist"}])
    monkeypatch.setattr(websetup, "PlexClient", lambda url, token, **k: plex)
    return tmp_path, plex, signed


def test_setup_on_the_page(plex_home, monkeypatch):
    tmp_path, plex, signed = plex_home
    saved = []
    setup = websetup.WebSetup(lambda: "https://booth.example", "Den PC", on_saved=lambda: saved.append(1))
    assert setup.start_plex() == "https://app.plex.tv/x" and setup.step == "plex_wait"
    signed.set()
    wait_for(lambda: setup.step == "server")
    assert setup.choices == ["Den PC", "Attic"]
    setup.choose(0)
    wait_for(lambda: setup.step == "library")
    assert setup.choices == ["Music", "Audiobooks"]
    setup.choose(0)
    wait_for(lambda: setup.step == "done")
    settings = config.load()
    assert settings["plex_url"] == onboard.LOCAL_PLEX and settings["plex_token"] == "server-token"
    assert settings["music_library"] == "Music" and settings["breaks_dir"] == str(tmp_path / "Radio Booth")
    assert settings["plex_client_id"].startswith("radiobooth-")
    assert plex.posts and saved == [1]

    codes = []

    def redeem(self, code, name):
        codes.append((self.server, code, name))
        if code != "ABCD-2345":
            raise LinkError("Booth DJ: That code didn't work.", 404)
        return "be_device"

    monkeypatch.setattr(websetup.Link, "redeem", redeem)
    with pytest.raises(onboard.SetupError, match="last 10 minutes"):
        setup.pair("WRONG")
    assert setup.pair(" ABCD-2345 ") == "Den PC"
    assert codes[-1] == ("https://booth.example", "ABCD-2345", "Den PC")
    assert config.load()["device_token"] == "be_device" and saved == [1, 1]


def test_setup_problems_are_shown_not_raised(plex_home, monkeypatch):
    tmp_path, plex, signed = plex_home
    monkeypatch.setattr(onboard, "owned_servers", lambda token, cid: [])
    setup = websetup.WebSetup(lambda: "https://booth.example", "pc", on_saved=lambda: None)
    setup.start_plex()
    signed.set()
    wait_for(lambda: setup.error)
    assert setup.step == "idle" and "no server of its own" in setup.error


def test_plex_on_another_computer_asks_for_the_shared_folder(plex_home, monkeypatch):
    tmp_path, plex, signed = plex_home
    monkeypatch.setattr(onboard, "owned_servers", lambda token, cid: [SERVER])
    monkeypatch.setattr(
        onboard, "reach", lambda server, token: ("https://192-168-1-20.plex.direct:32400", False)
    )
    plex.sections[:] = [
        {"title": "Music", "type": "artist"},
        {"title": "Radio Booth", "type": "artist", "Location": [{"path": "/srv/booth"}]},
    ]
    setup = websetup.WebSetup(lambda: "https://booth.example", "pc", on_saved=lambda: None)
    setup.start_plex()
    signed.set()
    wait_for(lambda: setup.step == "folder")
    assert "/srv/booth" in setup.folder_hint
    with pytest.raises(onboard.SetupError, match="isn't reachable"):
        setup.use_folder(str(tmp_path / "not-there"))
    setup.use_folder(f'"{tmp_path}"')
    assert setup.step == "done" and config.load()["breaks_dir"] == str(tmp_path)


def test_finishing_setup_starts_booth_and_its_sign_in_item_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    (tmp_path / "breaks").mkdir()
    installs = []
    monkeypatch.setattr(autostart, "installed", lambda platform=None, home=None: bool(installs))
    monkeypatch.setattr(autostart, "install", lambda platform=None: installs.append(platform) or "done")
    app = web.App("pc", platform="win32")
    started = []
    monkeypatch.setattr(app.engine, "start", lambda: started.append(1))
    config.save(
        {
            "server": "https://booth.example",
            "device_token": "be",
            **{k: "x" for k in websetup.PLEX_KEYS},
            "breaks_dir": str(tmp_path / "breaks"),
        }
    )
    app._saved()
    app._saved()  # changed later: no second sign-in item, but Booth restarts with the new settings
    assert installs == ["win32"] and started == [1, 1]


def test_the_engine_says_how_booth_is_doing(tmp_path, monkeypatch):
    (tmp_path / "breaks").mkdir()
    settings = {
        "server": "https://booth.example",
        "device_token": "be",
        "plex_url": "http://plex",
        "plex_token": "t",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path / "breaks"),
    }
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(k, raising=False)
    checkins = []

    def checkin(self):
        checkins.append(1)
        if len(checkins) == 1:
            raise LinkError("Could not reach Booth DJ at https://booth.example: offline")
        if len(checkins) == 2:
            return {"shows": [], "next_checkin_s": 0.01}
        raise LinkError("Booth DJ: unknown device", 401)

    monkeypatch.setattr(engine.Link, "checkin", checkin)
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    eng = engine.Engine(load=lambda: settings, retry_s=0.01, echo=False)
    states = []
    real_checked_in = eng._checked_in

    def checked_in():
        real_checked_in()
        states.append(eng.state)

    eng._checked_in = checked_in
    monkeypatch.setattr(engine, "run_link", _fast_run_link)
    eng.start()
    wait_for(lambda: eng.state == engine.NEEDS_PAIRING)
    assert states == [engine.ON_AIR] and eng.last_checkin
    assert any("trying again" in line for line in eng.lines)


def _fast_run_link(link, station, sleep):
    from radiobooth.link import run

    return run(link, station, sleep=lambda s: sleep(min(s, 0.01)))


def test_the_engine_waits_for_setup(monkeypatch):
    eng = engine.Engine(load=lambda: {}, echo=False)
    eng.start()
    wait_for(lambda: not eng._thread.is_alive())
    assert eng.state == engine.NOT_SET_UP


def test_updates_wait_until_no_show_is_on_its_way(monkeypatch):
    monkeypatch.setattr(update, "installed", lambda *a, **k: "app")
    busy = [True]
    restarted = []
    up = update.Updater(busy=lambda: busy[0], restart=lambda: restarted.append(up.message), auto=lambda: True)
    monkeypatch.setattr(update, "latest_release", lambda: {"version": "99.0", "assets": {}})
    monkeypatch.setattr(update, "apply", lambda release: release["version"])
    monkeypatch.setattr(update, "tidy", lambda: None)
    monkeypatch.setattr(update, "FIRST_CHECK_S", 0)

    def sleep(seconds):
        if restarted:  # the real app has exited by now: park the updater's thread
            threading.Event().wait()
        busy[0] = False  # a minute later, the show is in Plex

    monkeypatch.setattr(update.time, "sleep", sleep)
    up.start()
    wait_for(lambda: restarted)
    assert up.status()["latest"] == "99.0" and "installed" in restarted[0]


def test_a_restart_never_runs_two_booths_at_once(tmp_path, monkeypatch):
    (tmp_path / "breaks").mkdir()
    settings = {
        "server": "https://booth.example",
        "device_token": "be",
        "plex_url": "http://plex",
        "plex_token": "t",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path / "breaks"),
    }
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(k, raising=False)
    inside, most, release = [0], [0], threading.Event()
    lock = threading.Lock()

    def checkin(self):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        release.wait(5)  # a slow check-in, or a delivery in hand
        with lock:
            inside[0] -= 1
        return {"shows": [], "next_checkin_s": 5}

    monkeypatch.setattr(engine.Link, "checkin", checkin)
    eng = engine.Engine(load=lambda: settings, retry_s=0.01, echo=False)
    eng.start()
    wait_for(lambda: inside[0] == 1)
    eng.start()  # setup saved while the first is busy
    eng.start()
    time.sleep(0.2)
    release.set()
    wait_for(lambda: eng.state == engine.ON_AIR)
    assert most[0] == 1
    eng.stop()
    assert eng.state == engine.STOPPED


def test_a_cancelled_setup_changes_nothing(plex_home, monkeypatch):
    tmp_path, plex, signed = plex_home
    reached = threading.Event()
    go_on = threading.Event()

    def slow_reach(server, token):
        reached.set()
        go_on.wait(5)
        return onboard.LOCAL_PLEX, True

    monkeypatch.setattr(onboard, "reach", slow_reach)
    monkeypatch.setattr(onboard, "owned_servers", lambda token, cid: [SERVER])
    setup = websetup.WebSetup(lambda: "https://booth.example", "pc", on_saved=lambda: pytest.fail("saved"))
    setup.start_plex()
    signed.set()
    reached.wait(5)
    setup.cancel()  # "Done" on the page while Booth was still looking at the server
    go_on.set()
    time.sleep(0.3)
    assert setup.step == "idle" and not setup.error
    assert "plex_url" not in config.load()


def test_settings_saved_at_once_are_all_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    threads = [threading.Thread(target=config.update, args=({f"k{i}": i},)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert config.load() == {f"k{i}": i for i in range(20)}


def test_update_now_waits_for_a_show_in_hand(monkeypatch):
    monkeypatch.setattr(update, "installed", lambda *a, **k: "app")
    up = update.Updater(busy=lambda: True, restart=lambda: pytest.fail("restarted"), auto=lambda: True)
    up._release = {"version": "99.0", "assets": {}}
    monkeypatch.setattr(update, "apply", lambda release: pytest.fail("installed while busy"))
    up._install()
    assert "once the show" in up.message


def test_a_broken_reply_from_github_doesnt_stop_update_checks(monkeypatch):
    import http.client

    def cut_short():
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(update, "latest_release", cut_short)
    up = update.Updater(busy=lambda: False, restart=lambda: None, auto=lambda: True)
    up.check()
    assert up.state == "failed" and "Couldn't check" in up.message


def test_shows_are_asked_for_on_the_page(booth, monkeypatch):
    app, port, key, _ = booth
    status, data = act(port, key, "new_show", {"prompt": "rain"})
    assert status == 422 and "Connect Booth" in data["error"]  # not paired yet

    config.update({"device_token": "be_device", "server": "https://booth.example"})
    status, data = act(port, key, "new_show", {"prompt": "rain"})
    assert status == 422 and "on the air" in data["error"]  # it would wait for this Booth, so not yet
    app.engine.state = engine.ON_AIR
    asked, gets = [], []
    roster = {"djs": [{"id": "penrose", "name": "Penrose", "role": "night owl"}], "voices": ["A", "B"]}
    allowance = {"week": {"left": 50}, "text": "50 min of show time left this week."}

    def get(self, path):
        gets.append((self.server, self.token, path))
        if path == "/v0/me":
            return {"name": "Thomas", "roster": roster, "allowance": allowance}
        shows = [{"show_id": f"show_{i}", "status": "queued", "prompt": "p", "minutes": 40} for i in range(9)]
        return {"shows": shows, "allowance": allowance}

    def ask(self, request):
        asked.append((self.server, self.token, request))
        if request.get("minutes") == 5:
            raise LinkError("Booth DJ: Shows run 10 to 240 minutes.", 400)
        return {"show_id": "show_new", "status": "queued"}

    monkeypatch.setattr(web.Link, "get", get)
    monkeypatch.setattr(web.Link, "ask", ask)

    choices = {"minutes": 30, "dj": "penrose", "voice": "B", "dj_name": "Pen", "station": "Porch FM"}
    status, data = act(port, key, "new_show", {"prompt": "  Sunday chores ", **choices, "extra": "no"})
    assert status == 200 and data == {"show_id": "show_new"}
    assert asked == [("https://booth.example", "be_device", {"prompt": "Sunday chores", **choices})]
    assert config.load()["show_choices"] == choices  # remembered for next time; the prompt isn't

    status, data = act(port, key, "new_show", {"prompt": "x", "minutes": 5})
    assert status == 422 and data["error"] == "Shows run 10 to 240 minutes."
    assert act(port, key, "new_show", {"prompt": " "})[1]["error"] == "Say what the show is about."

    status, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    listed = json.loads(body)
    assert status == 200 and listed["roster"] == roster and listed["allowance"] == allowance
    assert len(listed["shows"]) == 6 and listed["choices"]["voice"] == "B"
    call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert [p for *_, p in gets] == ["/v0/me", "/v0/shows", "/v0/shows"]  # the DJs and voices, once
    assert call(port, "GET", "/api/shows")[0] == 403  # the page key, as for everything else


def test_the_page_says_when_radio_booth_is_out_of_reach(booth, monkeypatch):
    app, port, key, _ = booth
    config.update({"device_token": "be_device", "server": "https://booth.example"})

    def offline(self, path):
        raise LinkError("Could not reach Booth DJ at https://booth.example: no route", network=True)

    def unknown(self, request):
        raise LinkError("Booth DJ: Unknown Booth Engineer", 401)

    monkeypatch.setattr(web.Link, "get", offline)
    monkeypatch.setattr(web.Link, "ask", unknown)
    app.engine.state = engine.ON_AIR
    status, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 422 and "Is this computer online?" in json.loads(body)["error"]
    status, data = act(port, key, "new_show", {"prompt": "rain"})
    # Check-ins work, so it's paired: this Radio Booth just doesn't take shows from the page yet.
    assert status == 422 and "Ask on your phone" in data["error"]
    app.engine.state = engine.NEEDS_PAIRING
    assert "Connect it again" in app._said(LinkError("Booth DJ: Unknown Booth Engineer", 401)).args[0]
    assert "Try again" in app._said(LinkError("Booth DJ sent a reply that isn't JSON (cut short?).")).args[0]
    lost = LinkError("Could not reach Booth DJ at https://booth.example: timed out", network=True)
    assert "before asking again" in app._said(lost, asked=True).args[0]  # it may have arrived
    assert "Is this computer online?" in app._said(lost).args[0]
    assert "having trouble" in app._said(LinkError("Booth DJ: HTTP 503", 503)).args[0]
    assert "before asking again" in app._said(LinkError("Booth DJ: HTTP 503", 503), asked=True).args[0]

    # It talks to the server it's paired with, whatever BOOTH_SERVER says now.
    monkeypatch.setenv("BOOTH_SERVER", "https://elsewhere.example")
    assert app._link().server == "https://booth.example"

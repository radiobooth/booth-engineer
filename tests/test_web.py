import http.client
import json
import threading
import time

import pytest
from test_setup import SERVER, FakePlex

from radiobooth import autostart, config, engine, history, onboard, update, web, websetup
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


def test_state_has_the_phone_page_qr_code(booth, monkeypatch):
    app, port, key, link = booth
    monkeypatch.setenv("BOOTH_SERVER", "https://my.radiobooth.fm")
    status, _, body = call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})
    data = json.loads(body)
    assert data["server"] == "https://my.radiobooth.fm"
    assert data["phone_qr"] == web.phone_qr("https://my.radiobooth.fm")
    assert data["phone_qr"].startswith("data:image/svg+xml;base64,")


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
    monkeypatch.setattr(engine, "run_desks", _fast_run_desks)
    eng.start()
    wait_for(lambda: eng.state == engine.NEEDS_PAIRING)
    assert states == [engine.ON_AIR] and eng.last_checkin
    assert any("trying again" in line for line in eng.lines)


def _fast_run_desks(desks, sleep, unpaired):
    from radiobooth.link import run_all

    return run_all(desks, sleep=lambda s: sleep(min(s, 0.01)), unpaired=unpaired)


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


def test_another_person_can_share_this_booth(booth, monkeypatch):
    app, port, key, _ = booth
    config.update({"device_token": "be_own", "server": "https://booth.example", "name": "Den PC"})
    names = {
        "be_own": "Thomas",
        "be_jen": "Jennifer",
        "be_own2": "Thomas",
        "be_jen2": "Jennifer",
        "be_q": None,
    }
    codes = {"JENN-0001": "be_jen", "THOM-0001": "be_own2", "JENN-0002": "be_jen2", "QUIET-001": "be_q"}
    redeemed, gets, asked = [], [], []

    def redeem(self, code, name):
        redeemed.append((self.server, code, name))
        if code not in codes:
            raise LinkError("Booth DJ: That code didn't work.", 404)
        return codes[code]

    def get(self, path):
        gets.append((self.token, path))
        if path == "/v0/me":
            return {"name": names[self.token], "roster": {"djs": [{"id": "penrose"}]}}
        return {"shows": [{"show_id": self.token}], "allowance": {"text": self.token}}

    def ask(self, request):
        asked.append((self.token, request))
        return {"show_id": "show_new"}

    monkeypatch.setattr(web.Link, "redeem", redeem)
    monkeypatch.setattr(web.Link, "get", get)
    monkeypatch.setattr(web.Link, "ask", ask)
    monkeypatch.setattr(app.engine, "start", lambda: None)

    status, data = act(port, key, "add_person", {"code": "NOPE-0000"})
    assert status == 422 and "didn't work" in data["error"]
    status, data = act(port, key, "add_person", {"code": "JENN-0001"})
    assert status == 200 and data == {"name": "Jennifer"}
    # The server Booth checks in with, under a name of its own (see add_person).
    assert redeemed[-1] == ("https://booth.example", "JENN-0001", "Den PC (shared)")
    [jen] = config.people(config.load())
    assert jen["name"] == "Jennifer" and jen["device_token"] == "be_jen" and jen["id"].startswith("p_")
    assert jen["server"] == "https://booth.example"
    people = json.loads(call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})[2])[
        "account"
    ]
    assert people["people"] == [{"id": jen["id"], "name": "Jennifer", "unpaired": False, "plex_user": None}]

    # The New show form asks and lists as whoever it's for.
    _, _, body = call(port, "GET", f"/api/shows?who={jen['id']}", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert json.loads(body)["shows"] == [{"show_id": "be_jen"}]
    _, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert json.loads(body)["shows"] == [{"show_id": "be_own"}]
    assert config.load()["account_name"] == "Thomas"
    app.engine.state = engine.ON_AIR
    assert act(port, key, "new_show", {"prompt": "rain", "who": jen["id"]})[0] == 200
    assert act(port, key, "new_show", {"prompt": "sun"})[0] == 200
    assert asked == [("be_jen", {"prompt": "rain"}), ("be_own", {"prompt": "sun"})]
    status, _, body = call(port, "GET", "/api/shows?who=p_gone", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 422 and "any more" in json.loads(body)["error"]

    # A code from an account named like Booth's own changes nothing: it can't tell the accounts apart.
    status, data = act(port, key, "add_person", {"code": "THOM-0001"})
    assert status == 422 and "already makes shows for" in data["error"]
    assert config.load()["device_token"] == "be_own" and len(config.people(config.load())) == 1
    status, data = act(port, key, "add_person", {"code": "QUIET-001"})  # no name: not added as "Guest"
    assert status == 422 and "new code" in data["error"] and len(config.people(config.load())) == 1
    # The same person again, after their account forgot this computer, gets their place (and history) back.
    app.engine.unpaired = {jen["id"]}
    forgot = app._said(LinkError("Booth DJ: Unknown Booth Engineer", 401), who=jen["id"]).args[0]
    assert forgot.startswith("Jennifer's Booth account no longer knows this computer")
    assert act(port, key, "add_person", {"code": "JENN-0002"})[1] == {"name": "Jennifer"}
    assert [(p["id"], p["device_token"]) for p in config.people(config.load())] == [(jen["id"], "be_jen2")]

    # People paired with another Booth DJ never get its tokens.
    config.update({"server": "https://elsewhere.example"})
    assert config.people(config.load()) == []
    config.update({"server": "https://booth.example"})
    history.record(["101"], person=jen["id"])

    assert act(port, key, "remove_person", {"id": jen["id"]})[0] == 200
    assert config.people(config.load()) == [] and not history.path(jen["id"]).exists()
    assert act(port, key, "remove_person", {"id": jen["id"]})[0] == 422


def test_a_shared_booth_checks_in_and_delivers_for_each_person(tmp_path, monkeypatch):
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    settings = {
        "server": "https://booth.example",
        "device_token": "be_own",
        "plex_url": "http://plex",
        "plex_token": "t",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path),
        "people": [
            {"id": "p_jen", "device_token": "be_jen", "name": "Jennifer", "server": "https://booth.example"},
            {
                "id": "bad id",
                "device_token": "be_x",
                "server": "https://booth.example",
            },  # not Booth's: left out
            {"id": "p_old", "device_token": "be_old", "server": "https://old.example"},  # another server's
            {"id": "p_gone", "device_token": "be_gone", "server": "https://booth.example"},
        ],
    }
    log = []
    found, people = engine.desks(settings, log.append, lambda server, token: (server, token), skip={"p_gone"})
    assert [link for link, _ in found] == [
        ("https://booth.example", "be_own"),
        ("https://booth.example", "be_jen"),
    ]
    assert [p["id"] for p in people] == ["p_jen"]
    found[1][1].log("sent 3 tracks")
    assert log == ["Jennifer: sent 3 tracks"]

    delivered = []
    monkeypatch.setattr(
        engine.plex_target, "deliver", lambda *a, prefix="", **k: delivered.append(prefix) or _Done(prefix)
    )
    remembered = []
    monkeypatch.setattr(engine, "remember", lambda show_dir, log, person=None: remembered.append(person))
    assert found[1][1].deliver(tmp_path) == "Jennifer: x"
    assert found[0][1].deliver(tmp_path) == "x"
    assert delivered == ["Jennifer: ", ""] and remembered == ["p_jen", None]


class _Done:
    def __init__(self, prefix):
        self.title = f"{prefix}x"


def test_a_persons_playlists_can_be_shared_with_their_plex_user(booth, monkeypatch, tmp_path):
    app, port, key, _ = booth
    (tmp_path / "breaks").mkdir()
    config.update(
        {
            "device_token": "be_own",
            "server": "https://booth.example",
            "plex_url": "http://plex",
            "plex_token": "owner",
            "plex_client_id": "radiobooth-x",
            "breaks_library": "Radio Booth",
            "breaks_dir": str(tmp_path / "breaks"),
            "people": [
                {
                    "id": "p_jen",
                    "device_token": "be_jen",
                    "name": "Jennifer",
                    "server": "https://booth.example",
                }
            ],
        }
    )
    monkeypatch.setattr(app.engine, "start", lambda: None)
    monkeypatch.setattr(
        web.PlexClient, "get", lambda self, path: {"MediaContainer": {"machineIdentifier": "m1"}}
    )
    plex_users = [
        {"id": 3427736, "title": "evoljennifer", "home": True},
        {"id": 9, "title": "pat", "home": False},
    ]
    monkeypatch.setattr(web.plexshare, "users", lambda token, client_id: plex_users)
    asked = []

    def sees(token, client_id, machine, user_id, library):
        asked.append((token, client_id, machine, user_id, library))
        return user_id == 3427736

    monkeypatch.setattr(web.plexshare, "sees_library", sees)

    status, _, body = call(port, "GET", "/api/plex_users", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 200 and json.loads(body)["users"] == plex_users
    assert act(port, key, "person_plex", {"id": "p_jen", "user": "3427736"}) == (200, {"said": ""})
    assert asked == [("owner", "radiobooth-x", "m1", 3427736, "Radio Booth")]
    [jen] = config.people(config.load())
    assert jen["plex_user"] == {"id": 3427736, "title": "evoljennifer"}
    # Breaks the person's Plex user can't see would be silent: say so (and still share the playlists).
    status, data = act(port, key, "person_plex", {"id": "p_jen", "user": 9})
    assert status == 200 and "doesn't share the 'Radio Booth' library with pat" in data["said"]
    assert act(port, key, "person_plex", {"id": "p_jen", "user": 12345})[0] == 422  # not one of theirs
    assert act(port, key, "person_plex", {"id": "p_jen", "user": None}) == (200, {"said": ""})
    assert config.people(config.load())[0]["plex_user"] is None


def test_a_persons_new_playlist_is_shared_with_their_plex_user(tmp_path, monkeypatch):
    for k in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    settings = {
        "plex_url": "http://plex",
        "plex_token": "owner",
        "plex_client_id": "radiobooth-x",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path),
    }
    config.update({"plex_client_id": "radiobooth-x"})
    person = {"id": "p_jen", "name": "Jennifer", "plex_user": {"id": 3427736, "title": "evoljennifer"}}
    done = engine.plex_target.Delivery("777", "Jennifer: Rain", 3, 2, tmp_path, machine="m1")
    monkeypatch.setattr(engine.plex_target, "deliver", lambda *a, **k: done)
    monkeypatch.setattr(engine, "remember", lambda *a, **k: None)
    shared, log = [], []
    monkeypatch.setattr(engine.plexshare, "share_playlist", lambda *a: shared.append(a))
    assert engine.station(settings, log.append, person=person).deliver(tmp_path) == "Jennifer: Rain"
    assert shared == [("owner", "radiobooth-x", "m1", "777", "Jennifer: Rain", 3427736)]

    def refused(*a):
        raise web.PlexError("plex.tv said HTTP 403")

    monkeypatch.setattr(engine.plexshare, "share_playlist", refused)
    assert (
        engine.station(settings, log.append, person=person).deliver(tmp_path) == "Jennifer: Rain"
    )  # still in
    assert "Grant them access to it in Plex Web" in log[-1]


def test_shows_are_rated_and_breaks_flagged_on_the_page(booth, monkeypatch):
    """Feedback as on the phone page, sent with the device token of whoever the show was made for."""
    app, port, key, _ = booth
    config.update({"device_token": "be_own", "server": "https://booth.example"})
    jen = {"id": "p_jen", "name": "Jennifer", "device_token": "be_jen", "server": "https://booth.example"}
    config.update({"people": [jen]})
    gets, sent = [], []
    detail = {"show_id": "show_abc", "breaks": [{"id": "b01", "number": 1, "transcript": "Hi"}], "mine": {}}

    def get(self, path):
        gets.append((self.token, path))
        return detail

    def send(self, method, path, data):
        sent.append((self.token, method, path, data))
        if data.get("rating") == 9:
            raise LinkError("Booth DJ: A rating is 1 to 5 stars.", 400)
        return 204, {}

    monkeypatch.setattr(web.Link, "get", get)
    monkeypatch.setattr(web.Link, "send", send)
    cookie = {"Cookie": f"{web.COOKIE}={key}"}

    status, _, body = call(port, "GET", "/api/show?id=show_abc", headers=cookie)
    assert status == 200 and json.loads(body) == detail
    status, _, body = call(port, "GET", "/api/show?id=show_abc&who=p_jen", headers=cookie)
    assert status == 200 and gets == [("be_own", "/v0/shows/show_abc"), ("be_jen", "/v0/shows/show_abc")]
    for bad in ("../me", "show_abc/hide", "show_ABC%3F"):  # only Booth DJ's own ids go into a path
        status, _, body = call(port, "GET", f"/api/show?id={bad}", headers=cookie)
        assert status == 422 and json.loads(body)["error"] == "No such show."
    assert len(gets) == 2
    assert call(port, "GET", "/api/show?id=show_abc")[0] == 403  # the page key, as for everything else

    rate = {"show_id": "show_abc", "rating": 4, "note": "great", "reasons": ["x"], "extra": 1}
    assert act(port, key, "feedback", rate) == (200, {})
    flag = {
        "who": "p_jen",
        "show_id": "show_abc",
        "break": "b01",
        "reasons": ["said"],
        "note": "",
        "rating": 2,
    }
    assert act(port, key, "feedback", flag) == (200, {})
    assert (
        act(port, key, "feedback", {"who": "p_jen", "show_id": "show_abc", "break": "b01", "clear": True})[0]
        == 200
    )
    assert act(port, key, "feedback", {"show_id": "show_abc", "clear": True, "rating": 3})[0] == 200
    assert sent == [
        ("be_own", "PUT", "/v0/shows/show_abc/feedback", {"rating": 4, "note": "great"}),
        ("be_jen", "PUT", "/v0/shows/show_abc/breaks/b01/feedback", {"note": "", "reasons": ["said"]}),
        ("be_jen", "DELETE", "/v0/shows/show_abc/breaks/b01/feedback", {}),
        ("be_own", "DELETE", "/v0/shows/show_abc/feedback", {}),
    ]
    assert act(port, key, "feedback", {"show_id": "show_abc", "rating": 9}) == (
        422,
        {"error": "A rating is 1 to 5 stars."},
    )
    assert act(port, key, "feedback", {"show_id": "show_abc", "break": "b1/../x", "note": "n"})[0] == 422
    assert act(port, key, "feedback", {"show_id": "show_abc", "who": "p_gone", "rating": 3})[0] == 422
    assert len(sent) == 5

    # A Radio Booth that takes ratings only on the phone says so, rather than asking to pair again.
    def old_dj(self, method, path, data):
        raise LinkError("Booth DJ: Not signed in.", 401)

    monkeypatch.setattr(web.Link, "send", old_dj)
    status, data = act(port, key, "feedback", {"who": "p_jen", "show_id": "show_abc", "rating": 3})
    assert status == 422 and data["error"].startswith("Radio Booth can't take ratings from this page yet")

    def forgotten(self, path):  # Jennifer's account no longer knows this computer at all
        raise LinkError("Booth DJ: Unknown Booth Engineer", 401)

    monkeypatch.setattr(web.Link, "get", forgotten)
    status, data = act(port, key, "feedback", {"who": "p_jen", "show_id": "show_abc", "rating": 3})
    assert status == 422 and data["error"].startswith(
        "Jennifer's Booth account no longer knows this computer"
    )

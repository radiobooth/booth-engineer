import http.client
import json
import threading
import time

import pytest
from test_setup import SERVER, FakePlex

import radiobooth
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


def test_the_page_knows_its_version_to_spot_an_update(booth):
    # After a self-update the open page asks for /api/state from the new version: a different version than the
    # one that served page.js tells it to reload (or offer to, if a reload would lose typing).
    _, port, key, _ = booth
    status, _, js = call(port, "GET", "/page.js", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 200 and f'const PAGE_VERSION = "{radiobooth.__version__}";' in js.decode()
    status, _, data = call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert json.loads(data)["version"] == radiobooth.__version__


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
    (tmp_path / "share" / "booth").mkdir(parents=True)  # the share above the folder Plex watches
    setup.use_folder(f'"{tmp_path / "share"}"')
    assert setup.step == "done" and config.load()["breaks_dir"] == str(tmp_path / "share" / "booth")


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


def test_update_now_waits_for_a_show_in_hand_then_installs(monkeypatch):
    monkeypatch.setattr(update, "installed", lambda *a, **k: "app")
    busy = [True]
    restarted, logged = [], []
    up = update.Updater(
        busy=lambda: busy[0], restart=lambda: restarted.append(1), auto=lambda: True, log=logged.append
    )
    up._release = {"version": "99.0", "assets": {}}

    def apply(release):
        assert not busy[0], "installed while busy"
        return release["version"]

    monkeypatch.setattr(update, "apply", apply)

    def sleep(seconds):
        assert "once the show" in up.message and up.state == "installing"
        busy[0] = False  # the show is in Plex

    monkeypatch.setattr(update.time, "sleep", sleep)
    up._install(wait=True)
    assert restarted and up.state == "installed"
    assert any("installed" in line for line in logged)


def test_the_background_check_leaves_an_update_for_later_while_busy(monkeypatch):
    monkeypatch.setattr(update, "installed", lambda *a, **k: "app")
    up = update.Updater(busy=lambda: True, restart=lambda: pytest.fail("restarted"), auto=lambda: True)
    up._release = {"version": "99.0", "assets": {}}
    monkeypatch.setattr(update, "apply", lambda release: pytest.fail("installed while busy"))
    up._install()
    assert up.state == "available"  # still on offer, and the checks try again in a minute


def test_a_failed_update_is_logged_and_can_be_tried_again(monkeypatch):
    monkeypatch.setattr(update, "installed", lambda *a, **k: "app")
    logged = []
    up = update.Updater(busy=lambda: False, restart=lambda: None, auto=lambda: True, log=logged.append)
    up._release = {"version": "99.0", "assets": {}}
    up.latest = "99.0"

    def apply(release):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(update, "apply", apply)
    up._install(wait=True)
    status = up.status()
    assert status["state"] == "failed" and status["available"] and "Access is denied" in status["message"]
    assert any("Access is denied" in line for line in logged)


def test_a_broken_reply_from_github_doesnt_stop_update_checks(monkeypatch):
    import http.client

    def cut_short():
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(update, "latest_release", cut_short)
    up = update.Updater(busy=lambda: False, restart=lambda: None, auto=lambda: True)
    up.check()
    assert up.state == "failed" and "Couldn't check" in up.message


def test_the_page_lists_shows_and_asks_for_none(booth, monkeypatch):
    """Shows are asked for, rated and flagged on the phone page; Booth's page lists them to copy or remove."""
    app, port, key, _ = booth
    config.update({"device_token": "be_device", "server": "https://booth.example"})
    gets = []

    def get(self, path):
        gets.append((self.server, self.token, path))
        if path == "/v0/me":
            return {"name": "Thomas"}
        return {"shows": [{"show_id": f"show_{i}", "status": "queued"} for i in range(9)], "allowance": {}}

    monkeypatch.setattr(web.Link, "get", get)
    cookie = {"Cookie": f"{web.COOKIE}={key}"}
    status, _, body = call(port, "GET", "/api/shows", headers=cookie)
    listed = json.loads(body)
    assert status == 200 and list(listed) == ["shows"] and len(listed["shows"]) == 6
    call(port, "GET", "/api/shows", headers=cookie)
    # The shows each time; the account's name (for People) now and then.
    assert [p for *_, p in gets] == ["/v0/shows", "/v0/me", "/v0/shows"]
    assert config.load()["account_name"] == "Thomas"
    assert call(port, "GET", "/api/shows")[0] == 403  # the page key, as for everything else

    app.engine.state = engine.ON_AIR
    for action in ("new_show", "feedback"):
        assert act(port, key, action, {"prompt": "rain", "show_id": "show_1", "rating": 3}) == (
            422,
            {"error": "Booth doesn't know that button."},
        )
    assert call(port, "GET", "/api/show?id=show_1", headers=cookie)[0] == 404
    assert len(gets) == 3
    page_html = call(port, "GET", "/", headers=cookie)[2].decode()
    assert "Make a show on your phone" in page_html and "show-form" not in page_html


def test_the_shows_list_doesnt_need_the_account_name(booth, monkeypatch):
    app, port, key, _ = booth
    config.update({"device_token": "be_device", "server": "https://booth.example", "account_name": "Jen"})

    def get(self, path):
        if path == "/v0/me":
            raise LinkError("Booth DJ: HTTP 503", 503)
        return {"shows": [{"show_id": "show_1", "status": "queued"}]}

    monkeypatch.setattr(web.Link, "get", get)
    status, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 200 and json.loads(body)["shows"][0]["show_id"] == "show_1"
    assert app._named > 0  # not asked again on every poll while it fails
    app._named = -float("inf")

    # A name asked for with the old pairing, answered after a new one, isn't kept.
    def renamed(self, path):
        if path == "/v0/me":
            app._saved()  # paired again meanwhile
            return {"name": "Thomas"}
        return {"shows": []}

    monkeypatch.setattr(web.Link, "get", renamed)
    monkeypatch.setattr(app.engine, "start", lambda: None)
    monkeypatch.setattr(app.engine, "scan_music", lambda again=False: None)
    assert call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})[0] == 200
    assert config.load()["account_name"] == "Jen" and app._named == -float("inf")


def test_the_phone_card_opens_the_paired_radio_booth(booth, monkeypatch):
    _, port, key, _ = booth
    config.update({"device_token": "be_device", "server": "https://booth.example"})
    monkeypatch.setenv("BOOTH_SERVER", "https://elsewhere.example")
    data = json.loads(call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})[2])
    assert data["server"] == "https://booth.example" and data["phone_qr"] == web.phone_qr(
        "https://booth.example"
    )


def test_the_page_says_when_radio_booth_is_out_of_reach(booth, monkeypatch):
    app, port, key, _ = booth
    config.update({"device_token": "be_device", "server": "https://booth.example"})

    def offline(self, path):
        raise LinkError("Could not reach Booth DJ at https://booth.example: no route", network=True)

    monkeypatch.setattr(web.Link, "get", offline)
    status, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert status == 422 and "Is this computer online?" in json.loads(body)["error"]
    assert "was removed" in app._said(LinkError("Booth DJ: Unknown Booth Engineer", 401)).args[0]
    assert "Try again" in app._said(LinkError("Booth DJ sent a reply that isn't JSON (cut short?).")).args[0]
    assert "having trouble" in app._said(LinkError("Booth DJ: HTTP 503", 503)).args[0]
    assert app._said(LinkError("Booth DJ: Shows run 10 to 240 minutes.", 400)).args[0].startswith("Shows run")

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
    redeemed, gets = [], []

    def redeem(self, code, name):
        redeemed.append((self.server, code, name))
        if code not in codes:
            raise LinkError("Booth DJ: That code didn't work.", 404)
        return codes[code]

    def get(self, path):
        gets.append((self.token, path))
        if path == "/v0/me":
            return {"name": names[self.token]}
        return {"shows": [{"show_id": self.token}]}

    monkeypatch.setattr(web.Link, "redeem", redeem)
    monkeypatch.setattr(web.Link, "get", get)
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

    # The shows list lists as whoever is picked.
    _, _, body = call(port, "GET", f"/api/shows?who={jen['id']}", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert json.loads(body)["shows"] == [{"show_id": "be_jen"}]
    _, _, body = call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert json.loads(body)["shows"] == [{"show_id": "be_own"}]
    assert config.load()["account_name"] == "Thomas"
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
    assert forgot.startswith("This computer was removed from Jennifer's Radio Booth")
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

    def deliver(*a, prefix="", **_):
        delivered.append(prefix)
        return _Done(prefix, a[3])

    monkeypatch.setattr(engine.plex_target, "deliver", deliver)
    remembered = []
    monkeypatch.setattr(engine, "remember", lambda show_dir, log, person=None: remembered.append(person))
    assert found[1][1].deliver(tmp_path) == "Jennifer: x"
    assert found[0][1].deliver(tmp_path) == "x"
    assert delivered == ["Jennifer: ", ""] and remembered == ["p_jen", None]


class _Done:
    def __init__(self, prefix, dest):
        self.title, self.folder = f"{prefix}x", dest / "show"


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


def test_music_in_a_folder_set_up_listed_and_removed_on_the_page(booth, monkeypatch, tmp_path):
    from test_deliver import make_show
    from test_folder import tagged

    from radiobooth.targets import playlist

    app, port, key, _ = booth
    music, shows = tmp_path / "Music", tmp_path / "Booth shows"
    tagged(music, "a/1.flac", TITLE="One", ARTIST="A")
    status, data = act(port, key, "music_folder", {"music": str(tmp_path / "nope"), "shows": ""})
    assert status == 422 and "can't find that music folder" in data["error"]
    assert act(port, key, "music_folder", {"music": str(music), "shows": str(shows)})[0] == 200
    state = json.loads(call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})[2])
    assert state["music"] | {"suggest": None} == {
        "kind": "folder",
        "ready": True,
        "folder": str(music.resolve()),
        "shows_folder": str(shows.resolve()),
        "suggest": None,
    }
    wait_for(lambda: app.engine.report is not None)  # read straight after setup, before pairing
    assert app.engine.report["used"] == 1

    show = make_show(tmp_path)
    playlist.deliver(show, shows, music, lambda _: ("a/1.flac", {}))
    config.update({"device_token": "be_device", "server": "https://booth.example"})

    def get(self, path):
        if path == "/v0/me":
            return {"name": "Thomas"}
        return {"shows": [{"show_id": i, "status": "delivered"} for i in ("show_abcdef123456", "show_gone")]}

    monkeypatch.setattr(web.Link, "get", get)
    listed = json.loads(call(port, "GET", "/api/shows", headers={"Cookie": f"{web.COOKIE}={key}"})[2])
    assert [s["on_disk"] for s in listed["shows"]] == [True, False]

    opened = []
    app.open_folder = opened.append
    assert act(port, key, "copy_show", {"show_id": "show_abcdef123456"})[0] == 200
    wait_for(lambda: app.copy and app.copy["finished"])
    copy = shows.resolve() / "Copies" / "Wipers On, Long Way Home"
    assert app.copy == {
        "show_id": "show_abcdef123456",
        "kind": "folder",
        "done": 6,
        "total": 6,
        "finished": True,
        "folder": str(copy),
        "missing": 0,
    }
    assert opened == [copy]
    state = json.loads(call(port, "GET", "/api/state", headers={"Cookie": f"{web.COOKIE}={key}"})[2])
    assert state["copy"]["folder"] == str(copy)
    assert act(port, key, "copy_show", {"show_id": "../../x"})[0] == 422
    assert act(port, key, "copy_show", {"show_id": "show_abcdef123456", "kind": "zip"})[0] == 422
    assert act(port, key, "copy_show", {"show_id": "show_abcdef123456", "kind": "file"})[0] == 200
    wait_for(lambda: app.copy["finished"])
    one = shows.resolve() / "Copies" / "Wipers On, Long Way Home.mp3"
    assert (
        app.copy["file"] == str(one) and one.exists() and app.copy["missing"] == 3
    )  # its breaks aren't audio
    assert opened[-1] == one.parent
    # A phone asking for that show's file gets the one made already; nothing's mixed twice at once.
    from radiobooth import engine as booth_engine

    st = booth_engine.station(config.load(), lambda m: None)
    sent = st.one_file("show_abcdef123456", "", tmp_path / "phone")
    assert sent.read_bytes() == one.read_bytes() and sent.parent == tmp_path / "phone"
    with playlist.MIXING:
        status, data = act(port, key, "copy_show", {"show_id": "show_abcdef123456"})
        assert status == 422 and "for a phone" in data["error"]
    assert act(port, key, "copy_show", {"show_id": "show_gone000000"})[0] == 200  # it says why when done
    wait_for(lambda: app.copy["finished"])
    assert "isn't in your Booth shows folder" in app.copy["error"]

    assert act(port, key, "remove_show", {"show_id": "show_abcdef123456"})[0] == 200
    assert not copy.exists() and not one.exists()
    assert playlist.shows(shows) == [] and (music / "a" / "1.flac").exists()
    status, data = act(port, key, "remove_show", {"show_id": "show_abcdef123456"})
    assert status == 422 and "isn't in your Booth shows folder" in data["error"]
    assert act(port, key, "remove_show", {"show_id": "../../x"})[0] == 422


def test_the_footer_links_to_the_license(booth):
    _, port, key, _ = booth
    status, _, body = call(port, "GET", "/", headers={"Cookie": f"{web.COOKIE}={key}"})
    assert (
        status == 200
        and f'href="{radiobooth.LICENSE_URL}"' in body.decode()
        and "__LICENSE_URL__" not in body.decode()
    )


def test_plex_shows_can_be_copied_and_removed_on_the_page(booth, monkeypatch, tmp_path):
    from test_plex_shows import FOLDER, SHOW, TITLE, PlexWithPlaylists
    from test_render import tone

    app, port, key, _ = booth
    dest = tmp_path / "radiobooth"
    (dest / FOLDER).mkdir(parents=True)
    tone(dest / FOLDER / "01.mp3", "libmp3lame", 2, 220, 0.3, rate=24000)
    tone(dest / FOLDER / "02.mp3", "libmp3lame", 2, 330, 0.3, rate=24000)
    song = tone(tmp_path / "1.flac", "flac", 3, 440, 0.3)
    plex = PlexWithPlaylists({"/library/parts/1/1/file.flac": song})
    monkeypatch.setattr(web, "PlexClient", lambda url, token: plex)
    monkeypatch.setattr(web, "default_shows_folder", lambda: tmp_path / "Booth shows")
    monkeypatch.setattr(web.onboard, "in_container", lambda: True)
    config.update(
        {
            "plex_url": "http://nas:32400",
            "plex_token": "tok",
            "music_library": "Music",
            "breaks_library": "Radio Booth",
            "breaks_dir": str(dest),
            "device_token": "be_device",
            "server": "https://booth.example",
        }
    )

    def get(self, path):
        if path == "/v0/me":
            return {"name": "Thomas"}
        return {
            "shows": [
                {"show_id": i, "status": "delivered", "title": TITLE} for i in (SHOW, "show_elsewhere1")
            ]
        }

    monkeypatch.setattr(web.Link, "get", get)
    cookie = {"Cookie": f"{web.COOKIE}={key}"}
    listed = json.loads(call(port, "GET", "/api/shows", headers=cookie)[2])
    assert [s.get("on_disk") for s in listed["shows"]] == [True, None]  # the other was made elsewhere

    status, data = act(port, key, "copy_show", {"show_id": SHOW, "title": TITLE})
    assert status == 422 and "BOOTH_SHOWS_FOLDER" in data["error"]  # a copy would stay in the container
    monkeypatch.setattr(web.onboard, "in_container", lambda: False)
    opened = []
    app.open_folder = opened.append
    assert act(port, key, "copy_show", {"show_id": SHOW, "title": TITLE})[0] == 200
    wait_for(lambda: app.copy and app.copy["finished"])
    copy = tmp_path / "Booth shows" / "Copies" / "Wipers On, Long Way Home"
    assert app.copy["folder"] == str(copy) and app.copy["missing"] == 2 and opened == [copy]

    assert act(port, key, "remove_show", {"show_id": SHOW, "title": TITLE})[0] == 200
    assert plex.deleted == ["5555"] and not (dest / FOLDER).exists() and not copy.exists()
    listed = json.loads(call(port, "GET", "/api/shows", headers=cookie)[2])
    assert listed["shows"][0]["on_disk"] is False
    status, data = act(port, key, "remove_show", {"show_id": SHOW})
    assert status == 422 and "breaks aren't in Booth's breaks folder" in data["error"]


def test_a_new_pairing_with_someone_elses_code_asks_first(booth, monkeypatch):
    app, port, key, _ = booth
    monkeypatch.setenv("BOOTH_SERVER", "https://booth.example")
    config.update({"device_token": "be_own", "server": "https://booth.example", "name": "Den PC"})
    names = {"be_own": "Thomas", "be_jen": "Jennifer", "be_jen2": "Jennifer", "be_own2": "Thomas"}
    codes = {"JENN-0001": "be_jen", "JENN-0002": "be_jen2", "THOM-0001": "be_own2"}
    redeemed = []

    def redeem(self, code, name):
        redeemed.append((code, name))
        return codes[code]

    def get(self, path):
        if self.token not in names:
            raise LinkError("Booth DJ: Unknown Booth Engineer", 401)
        return {"name": names[self.token]}

    monkeypatch.setattr(web.Link, "redeem", redeem)
    monkeypatch.setattr(web.Link, "get", get)
    monkeypatch.setattr(app.engine, "start", lambda: None)

    # Jennifer's code in Booth's own pairing box: nothing changes until the page's question is answered.
    status, data = act(port, key, "pair", {"code": "JENN-0001"})
    assert status == 200 and data == {"ask": {"own": "Thomas", "theirs": "Jennifer"}}
    assert config.load()["device_token"] == "be_own" and config.people(config.load()) == []
    assert act(port, key, "pair_choice", {"choice": "maybe"})[0] == 422
    assert act(port, key, "pair_choice", {"choice": "add"}) == (200, {"added": "Jennifer"})
    [jen] = config.people(config.load())
    assert jen["device_token"] == "be_jen" and config.load()["device_token"] == "be_own"
    status, data = act(port, key, "pair_choice", {"choice": "add"})  # answered once only
    assert status == 422 and "new code" in data["error"]

    # Asked again, and switched: Jennifer's account becomes this computer's own, and not also a person on it.
    assert "ask" in act(port, key, "pair", {"code": "JENN-0002"})[1]
    assert act(port, key, "pair_choice", {"choice": "switch"}) == (200, {"name": "Den PC"})
    settings = config.load()
    assert settings["device_token"] == "be_jen2" and settings["account_name"] == "Jennifer"
    assert config.people(settings) == []

    # The question doesn't stay open for ever.
    assert "ask" in act(port, key, "pair", {"code": "THOM-0001"})[1]
    app._pending["at"] -= web.PAIR_ASK_S + 1
    assert act(port, key, "pair_choice", {"choice": "switch"})[0] == 422
    assert config.load()["device_token"] == "be_jen2"

    # The same account again, or one this computer's pairing was forgotten by, just pairs.
    names["be_jen3"] = "Jennifer"
    codes["JENN-0003"] = "be_jen3"
    assert act(port, key, "pair", {"code": "JENN-0003"}) == (200, {"name": "Den PC"})
    del names["be_jen3"]  # Radio Booth forgot it
    assert act(port, key, "pair", {"code": "THOM-0001"}) == (200, {"name": "Den PC"})
    assert config.load()["device_token"] == "be_own2"


def test_page_server_stays_quiet_when_the_page_hangs_up(capsys):
    server = web.PageServer(("127.0.0.1", 0), web.BaseHTTPRequestHandler, bind_and_activate=False)
    try:
        try:
            raise BrokenPipeError(32, "Broken pipe")
        except BrokenPipeError:
            server.handle_error(None, ("127.0.0.1", 1))
        assert capsys.readouterr().err == ""
        try:
            raise ValueError("real trouble")
        except ValueError:
            server.handle_error(None, ("127.0.0.1", 1))
        assert "real trouble" in capsys.readouterr().err
    finally:
        server.server_close()

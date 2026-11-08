import json
import sys
from pathlib import Path

import pytest

from radiobooth import autostart, cli, config, onboard, setup_flow
from radiobooth.onboard import SetupError

SERVER = {
    "name": "Den PC",
    "clientIdentifier": "abc",
    "provides": "server",
    "owned": True,
    "accessToken": "server-token",
    "connections": [
        {"uri": "https://relay.plex.direct:8443", "local": False, "relay": True},
        {"uri": "https://203-0-113-5.plex.direct:32400", "local": False, "relay": False},
        {"uri": "https://192-168-1-20.plex.direct:32400", "local": True, "relay": False},
    ],
}


def test_sign_in_opens_plex_and_waits_for_the_token():
    calls, opened, said = [], [], []
    replies = iter([{"id": 7, "code": "pin-code"}, {"authToken": None}, {"authToken": "acct-token"}])

    def call(method, path, client_id, token=None, params=None):
        calls.append((method, path, params))
        return next(replies)

    token = onboard.sign_in(
        "cid", open_browser=opened.append, say=said.append, call=call, sleep=lambda s: None
    )
    assert token == "acct-token"
    assert calls[0] == ("POST", "/pins", {"strong": "true"})
    assert calls[1] == ("GET", "/pins/7", {"code": "pin-code"})  # strong PINs are polled with their code
    assert opened[0].startswith("https://app.plex.tv/auth#?clientID=cid&code=pin-code&context")
    assert "Radio+Booth" in opened[0] and opened[0] in said[1]


def test_sign_in_gives_up_eventually():
    def call(method, path, *a, **k):
        return {"id": 1, "code": "c"} if method == "POST" else {"authToken": None}

    with pytest.raises(SetupError, match="in time"):
        onboard.sign_in("c", open_browser=print, say=print, call=call, sleep=lambda s: None, timeout=6)


def test_only_owned_servers_count():
    shared = {**SERVER, "owned": False}
    player = {"name": "Phone", "provides": "client,player", "owned": True}
    found = onboard.owned_servers("t", "c", call=lambda *a, **k: [SERVER, shared, player])
    assert found == [SERVER]


def test_plex_on_this_computer_is_reached_directly():
    probe = lambda url, token=None: {"machineIdentifier": "abc"}  # noqa: E731
    url, here = onboard.reach(SERVER, "t", probe=probe, contained=lambda: False)
    assert (url, here) == (onboard.LOCAL_PLEX, True)


def test_plex_on_the_host_of_a_container_is_not_here():
    # Host networking: Plex answers on 127.0.0.1, but its folders aren't the container's.
    probe = lambda url, token=None: {"machineIdentifier": "abc"}  # noqa: E731
    url, here = onboard.reach(SERVER, "t", probe=probe, contained=lambda: True)
    assert (url, here) == ("https://192-168-1-20.plex.direct:32400", False)


def test_container_is_recognised_by_the_image_setting(monkeypatch):
    monkeypatch.setenv("BOOTH_IN_CONTAINER", "1")
    assert onboard.in_container()


def test_plex_elsewhere_prefers_the_local_network():
    tried = []

    def probe(url, token=None):
        tried.append(url)
        return {"machineIdentifier": "abc"} if "192-168" in url or "203-0" in url else None

    found = onboard.reach(SERVER, "t", probe=probe, contained=lambda: False)
    assert found == ("https://192-168-1-20.plex.direct:32400", False)
    assert tried[0] == onboard.LOCAL_PLEX and tried[1].startswith("https://192-168")


def test_unreachable_plex_says_so():
    with pytest.raises(SetupError, match="couldn't connect"):
        onboard.reach(SERVER, "t", probe=lambda *a, **k: None, contained=lambda: False)


class FakePlex:
    def __init__(self, sections):
        self.sections, self.posts = sections, []

    def get(self, path, params=None):
        return {"MediaContainer": {"Directory": self.sections}}

    def request(self, method, path, params=None):
        self.posts.append((method, path, params))
        self.sections.append(
            {"title": params["name"], "type": "artist", "Location": [{"path": params["location"]}]}
        )
        return {}


def test_breaks_library_is_made_for_its_own_folder(tmp_path):
    plex = FakePlex([{"title": "Music", "type": "artist"}])
    section = onboard.make_breaks_library(plex, tmp_path / "Radio Booth")
    assert (tmp_path / "Radio Booth").is_dir() and section["title"] == "Radio Booth"
    ((method, path, params),) = plex.posts
    assert (method, path) == ("POST", "/library/sections")
    assert params["type"] == "artist" and params["location"] == str(tmp_path / "Radio Booth")


def test_breaks_folder_stays_out_of_watched_folders(tmp_path, monkeypatch):
    home, data = tmp_path / "home", tmp_path / "data"
    first, second = home / "Radio Booth", data / "Radio Booth" / "breaks"
    monkeypatch.setattr(onboard, "breaks_dir_candidates", lambda: [first, second])
    assert onboard.default_breaks_dir([str(home / "Music")]) == first
    assert onboard.default_breaks_dir([str(home)]) == second  # a library watching the whole home
    assert onboard.default_breaks_dir([str(first / "old")]) == second  # a library inside it
    with pytest.raises(SetupError, match="empty folder of its own"):
        onboard.default_breaks_dir([str(data), str(first)])


@pytest.mark.skipif(not hasattr(onboard.os, "getuid"), reason="Unix permissions")
def test_breaks_folder_is_one_plex_can_read_when_it_runs_as_another_user(tmp_path, monkeypatch, request):
    # pytest's own temp folders are private (0700): open them to other users for the test, as /srv would be.
    for folder in [tmp_path, *tmp_path.parents]:
        if folder.stat().st_uid == onboard.os.getuid() and not folder.stat().st_mode & 0o001:
            mode = folder.stat().st_mode
            folder.chmod(mode | 0o001)
            request.addfinalizer(lambda folder=folder, mode=mode: folder.chmod(mode))
    home, srv = tmp_path / "home", tmp_path / "srv"
    (srv / "music").mkdir(parents=True)
    home.mkdir(mode=0o750)  # like Ubuntu's home folders: other users can't look inside
    home.chmod(0o750)
    monkeypatch.setattr(onboard, "breaks_dir_candidates", lambda: [home / "Radio Booth"])
    monkeypatch.setattr(onboard, "_groups", lambda uid: set())
    plex = onboard.os.getuid() + 1
    assert onboard.default_breaks_dir([str(srv / "music")]) == home / "Radio Booth"  # same user: fine
    assert onboard.default_breaks_dir([str(srv / "music")], onboard.os.getuid()) == home / "Radio Booth"
    assert onboard.default_breaks_dir([str(srv / "music")], plex) == srv / "Radio Booth"
    if onboard.os.geteuid() == 0:
        return  # root can write anywhere, so the rest doesn't apply
    srv.chmod(0o500)  # and Booth can't write next to the music either
    try:
        with pytest.raises(SetupError, match="Plex can read"):
            onboard.default_breaks_dir([str(srv / "music")], plex)
    finally:
        srv.chmod(0o755)


def test_plex_user_is_found_from_its_process(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard.sys, "platform", "linux")
    for pid, name, uid in (("1", "systemd", "0"), ("42", "Plex Media Serv", "998"), ("self", "x", "1")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "status").write_text(f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    assert onboard.plex_user_id(tmp_path) == 998
    (tmp_path / "42" / "status").write_text("Name:\tbash\nUid:\t998\n")
    assert onboard.plex_user_id(tmp_path) is None
    monkeypatch.setattr(onboard.sys, "platform", "darwin")
    assert onboard.plex_user_id(tmp_path) is None


def test_folders_on_other_drives_never_overlap(tmp_path, monkeypatch):
    def other_drive(paths):
        raise ValueError("Paths don't have the same drive")  # what Windows says for C:\\ and D:\\

    monkeypatch.setattr(onboard.os.path, "commonpath", other_drive)
    assert onboard.overlaps(tmp_path / "Radio Booth", "D:/Music") is False


def test_library_folders_lists_every_watched_folder():
    plex = FakePlex(
        [
            {"title": "Music", "Location": [{"path": "/m1"}, {"path": "/m2"}]},
            {"title": "Films", "Location": [{"path": "/films"}]},
            {"title": "Empty"},
        ]
    )
    assert onboard.library_folders(plex) == ["/m1", "/m2", "/films"]


def test_breaks_candidates_are_never_under_music():
    assert all("Music" not in folder.parts for folder in onboard.breaks_dir_candidates())


def test_choose_asks_only_when_there_is_a_choice():
    said = []
    assert onboard.choose("?", ["a"], str, ask=None, say=said.append) == "a"
    answers = iter(["9", "2"])
    assert onboard.choose("Which?", ["a", "b"], str, ask=lambda q: next(answers), say=said.append) == "b"
    assert "  2. b" in said and "That isn't one of the numbers." in said


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setattr(onboard, "breaks_dir_candidates", lambda: [tmp_path / "Radio Booth"])
    monkeypatch.setattr(onboard, "sign_in", lambda client_id, **k: "acct-token")
    monkeypatch.setattr(onboard, "owned_servers", lambda token, client_id: [SERVER])
    monkeypatch.setattr(onboard, "reach", lambda server, token: (onboard.LOCAL_PLEX, True))
    monkeypatch.setattr(onboard, "plex_user_id", lambda: None)
    plex = FakePlex([{"title": "Music", "type": "artist"}, {"title": "Audiobooks", "type": "artist"}])
    monkeypatch.setattr(setup_flow, "PlexClient", lambda url, token, **k: plex)
    codes = []

    def redeem(self, code, name):
        codes.append(code)
        if code != "ABCD-2345":
            from radiobooth.link import LinkError

            raise LinkError("Booth DJ: That code didn't work.", 404)
        return "be_device"

    monkeypatch.setattr(setup_flow.Link, "redeem", redeem)
    return tmp_path, plex, codes


def test_guided_setup_end_to_end(home, monkeypatch, capsys):
    tmp_path, plex, codes = home
    monkeypatch.setattr(cli, "run", lambda args: 7)  # then it stays connected in the same window
    answers = iter(["1", "WRONG-CODE", "ABCD-2345", "n"])
    code = setup_flow.guided(
        "https://booth.example", "den-pc", ask=lambda q: next(answers), open_browser=None
    )
    assert code == 7
    saved = config.load()
    assert saved["plex_url"] == onboard.LOCAL_PLEX and saved["plex_token"] == "server-token"
    assert saved["music_library"] == "Music" and saved["breaks_library"] == "Radio Booth"
    assert saved["breaks_dir"] == str(tmp_path / "Radio Booth")
    assert saved["device_token"] == "be_device" and saved["server"] == "https://booth.example"
    assert saved["plex_client_id"].startswith("radiobooth-")
    assert codes == ["WRONG-CODE", "ABCD-2345"]
    out = capsys.readouterr().out
    assert "Made a Plex library called 'Radio Booth'" in out and "That code didn't work" in out


def test_setup_keeps_what_works_and_stops_cleanly(home, monkeypatch, capsys):
    tmp_path, plex, _ = home
    (tmp_path / "Radio Booth").mkdir(parents=True)
    plex.sections.append(
        {
            "title": "Radio Booth",
            "type": "artist",
            "Location": [{"path": str(tmp_path / "Radio Booth")}],
        }
    )
    answers = iter(["1"])

    def ask(q):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    assert setup_flow.guided("https://booth.example", "x", ask=ask, open_browser=None) == 1
    assert plex.posts == []  # the existing breaks library is used, not made again
    assert config.load()["breaks_dir"] == str(tmp_path / "Radio Booth")
    assert "what's done so far is kept" in capsys.readouterr().out


def test_remote_plex_without_a_breaks_library_explains(home, monkeypatch):
    monkeypatch.setattr(
        onboard, "reach", lambda server, token: ("https://192-168-1-20.plex.direct:32400", False)
    )
    with pytest.raises(SetupError, match="once the library is there"):
        setup_flow.plex_step({}, ask=lambda q: "1", open_browser=None)


def test_autostart_files(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "command", lambda: [r"C:\Users\Al\Downloads\booth.exe"])
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    menu = tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs"
    (menu / "Startup").mkdir(parents=True)
    (menu / "Startup" / "Radio Booth.cmd").write_text("how 0.1 started")
    (menu / "Radio Booth setup.lnk").write_text("0.1's setup shortcut")
    ran = []
    assert "Windows" in autostart.install("win32", tmp_path, run=lambda *a, **k: ran.append(a[0]))
    assert (
        not (menu / "Startup" / "Radio Booth.cmd").exists() and not (menu / "Radio Booth setup.lnk").exists()
    )
    shortcuts = [args[-1] for args in ran if args[0] == "powershell"]  # shortcuts, so no window flashes up
    assert str(menu / "Startup" / "Radio Booth.lnk") in shortcuts[0]
    assert "$s.Arguments = 'app --background'" in shortcuts[0]
    assert str(menu / "Radio Booth.lnk") in shortcuts[1] and "$s.Arguments = ''" in shortcuts[1]
    assert autostart.installed("win32", tmp_path) is False  # PowerShell didn't really run here
    (menu / "Startup" / "Radio Booth.lnk").write_text("lnk")
    assert autostart.installed("win32", tmp_path)
    autostart.remove("win32", tmp_path)
    assert not autostart.installed("win32", tmp_path)

    assert "Mac" in autostart.install("darwin", tmp_path, run=lambda *a, **k: ran.append(a[0]))
    plist = (tmp_path / "Library/LaunchAgents/com.radiobooth.engineer.plist").read_text()
    assert "<string>app</string>" in plist and ran[-1][:2] == ["launchctl", "load"]
    assert "<key>ThrottleInterval</key>" in plist  # a Booth that can't start isn't retried every 10 s
    assert autostart.installed("darwin", tmp_path)
    autostart.remove("darwin", tmp_path)
    assert not autostart.installed("darwin", tmp_path)

    autostart.install("linux", tmp_path, run=lambda *a, **k: ran.append(a[0]))
    unit = (tmp_path / ".config/systemd/user/radiobooth.service").read_text()
    assert 'ExecStart="C:\\Users\\Al\\Downloads\\booth.exe" run' not in unit and "run" in unit
    assert ran[-1][-1] == "radiobooth.service"


def test_commands_read_settings_saved_by_setup(tmp_path, monkeypatch, capsys):
    for var in ("PLEX_URL", "PLEX_TOKEN", "BOOTH_BREAKS_LIBRARY", "BOOTH_BREAKS_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    assert cli.main(["deliver", str(tmp_path)]) == 1
    assert "booth setup" in capsys.readouterr().err
    config.save(
        {"plex_url": "http://p", "plex_token": "t", "breaks_library": "RB", "breaks_dir": str(tmp_path)}
    )
    assert cli.delivery_settings("deliver", None, None) == ("http://p", "t", "RB", str(tmp_path))
    monkeypatch.setenv("PLEX_URL", "http://env")  # the environment still wins
    assert cli.delivery_settings("deliver", None, None)[0] == "http://env"


def test_only_one_booth_runs_at_a_time(tmp_path):
    first = cli.single_instance(tmp_path / "run.lock")
    assert first is not None
    assert cli.single_instance(tmp_path / "run.lock") is None
    first.close()
    assert cli.single_instance(tmp_path / "run.lock") is not None


def test_config_survives_a_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "c.json"))
    config.save({"a": 1})
    assert json.loads(Path(tmp_path / "c.json").read_text()) == {"a": 1}


def test_the_windows_app_keeps_a_copy_of_itself(tmp_path, monkeypatch):
    exe = tmp_path / "Downloads" / "RadioBooth-Windows.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ app")
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    kept = autostart.keep_app([str(exe)], tmp_path, "win32")
    assert kept == [str(tmp_path / "Local" / "Radio Booth" / "RadioBooth.exe")]
    assert Path(kept[0]).read_bytes() == b"MZ app"
    assert autostart.keep_app(kept, tmp_path, "win32") == kept  # already there: left alone


def test_the_mac_app_runs_from_its_own_folder_not_downloads(tmp_path, monkeypatch):
    app = tmp_path / "Downloads" / "Radio Booth.command"
    app.parent.mkdir()
    app.write_bytes(b"app")
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart, "command", lambda: [str(app)])
    autostart.install("darwin", tmp_path, run=lambda *a, **k: None)
    kept = tmp_path / "Library" / "Application Support" / "Radio Booth" / "Radio Booth"
    assert kept.read_bytes() == b"app"
    plist = (tmp_path / "Library/LaunchAgents/com.radiobooth.engineer.plist").read_text()
    assert f"<string>{kept}</string>" in plist and "Downloads" not in plist


@pytest.mark.skipif(sys.platform != "win32", reason="makes a real Windows shortcut")
def test_start_menu_shortcuts_really_get_made(tmp_path):
    import subprocess

    link = tmp_path / "Radio Booth's setup.lnk"
    script = autostart.shortcut_script(link, [r"C:\Windows\notepad.exe"], "app --background")
    autostart.checked(subprocess.run, ["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    assert link.is_file()


def test_a_failed_service_start_is_an_error(tmp_path):
    from types import SimpleNamespace

    def run(args, **k):
        bad = args[:2] == ["launchctl", "load"]
        return SimpleNamespace(returncode=1 if bad else 0, stderr="Load failed: 5: Input/output error\n")

    with pytest.raises(OSError, match="Input/output error"):
        autostart.install("darwin", tmp_path, run=run)


def test_an_existing_pairing_can_be_replaced(home, monkeypatch):
    tmp_path, plex, codes = home
    answers = iter(["n", "ABCD-2345"])
    out = setup_flow.pair_step(
        {"device_token": "be_old"}, "https://booth.example", "pc", ask=lambda q: next(answers)
    )
    assert out["device_token"] == "be_device" and codes == ["ABCD-2345"]


def test_setup_reuses_the_saved_server(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("BOOTH_SERVER", raising=False)
    config.save({"server": "https://staging.example"})
    seen = []
    monkeypatch.setattr(setup_flow, "guided", lambda server, name: seen.append(server) or 0)
    assert cli.main(["setup"]) == 0 and seen == ["https://staging.example"]


def test_a_dead_pairing_is_not_offered_again(home, monkeypatch):
    tmp_path, plex, codes = home
    config.save({"device_token": "be_dead"})
    answers = iter(["ABCD-2345"])
    out = setup_flow.pair_step(
        config.load(), "https://booth.example", "x", ask=lambda q: next(answers), offer_keep=False
    )
    assert out["device_token"] == "be_device" and codes == ["ABCD-2345"]


def test_a_tidied_away_breaks_folder_is_made_again(home, monkeypatch):
    tmp_path, plex, _ = home
    gone = tmp_path / "Radio Booth"
    plex.sections.append({"title": "Radio Booth", "type": "artist", "Location": [{"path": str(gone)}]})
    out = setup_flow.plex_step({}, ask=lambda q: "1", open_browser=None)
    assert out["breaks_dir"] == str(gone) and gone.is_dir() and plex.posts == []


def test_sign_in_rides_out_a_moment_offline():
    replies = iter(
        [{"id": 7, "code": "c"}, SetupError("offline"), SetupError("offline"), {"authToken": "tok"}]
    )

    def call(*a, **k):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    assert onboard.sign_in("cid", open_browser=print, say=print, call=call, sleep=lambda s: None) == "tok"


def test_a_sign_in_page_instead_of_plex_is_explained(monkeypatch):
    class Page:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>Accept the Wi-Fi terms</html>"

    monkeypatch.setattr(onboard.urllib.request, "urlopen", lambda req, timeout: Page())
    with pytest.raises(SetupError, match="something unexpected"):
        onboard.plex_tv("POST", "/pins", "cid")


def test_a_saved_plex_sign_in_that_plex_refuses_is_not_offered(home, monkeypatch, capsys):
    from radiobooth.sources.plex import PlexAuthError

    tmp_path, plex, _ = home
    (tmp_path / "Radio Booth").mkdir(parents=True)
    saved = {
        "plex_url": "http://plex:32400",
        "plex_token": "stale",
        "music_library": "Music",
        "breaks_library": "Radio Booth",
        "breaks_dir": str(tmp_path / "Radio Booth"),
    }

    class Refusing:
        def get(self, path, params=None):
            raise PlexAuthError()

    monkeypatch.setattr(
        setup_flow, "PlexClient", lambda url, token, **k: Refusing() if token == "stale" else plex
    )
    out = setup_flow.plex_step(
        saved, ask=lambda q: pytest.fail(f"asked {q!r}") if "Keep it" in q else "1", open_browser=None
    )
    assert out["plex_token"] == "server-token"
    assert "no longer accepts Booth's saved sign-in" in capsys.readouterr().out


def test_an_older_versions_sign_in_item_is_noticed(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    startup = tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True)
    assert not autostart.outdated("win32", tmp_path)
    (startup / "Radio Booth.cmd").write_text("booth run")
    assert autostart.outdated("win32", tmp_path)

    plist = tmp_path / "Library/LaunchAgents/com.radiobooth.engineer.plist"
    assert not autostart.outdated("darwin", tmp_path)
    plist.parent.mkdir(parents=True)
    plist.write_text(
        autostart.mac_plist(["/Applications/Radio Booth.app/Contents/MacOS/Radio Booth"], tmp_path)
    )
    assert not autostart.outdated("darwin", tmp_path)
    plist.write_text("<plist><string>run</string></plist>")
    assert autostart.outdated("darwin", tmp_path)


def test_the_start_menu_entry_is_made_without_start_at_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    programs = tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs"
    programs.mkdir(parents=True)
    (programs / "Radio Booth setup.lnk").write_text("0.1's setup shortcut")
    ran = []
    autostart.start_menu(tmp_path, run=lambda a, **k: ran.append(a), cmd=[r"C:\Booth\RadioBooth.exe"])
    (script,) = [a[-1] for a in ran]
    assert str(programs / "Radio Booth.lnk") in script and "$s.Arguments = ''" in script
    assert not (programs / "Radio Booth setup.lnk").exists()
    assert not (programs / "Startup").exists()  # starting at sign-in is a separate choice

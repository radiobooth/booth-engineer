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
    url, here = onboard.reach(SERVER, "t", probe=lambda url, token=None: {"machineIdentifier": "abc"})
    assert (url, here) == (onboard.LOCAL_PLEX, True)


def test_plex_elsewhere_prefers_the_local_network():
    tried = []

    def probe(url, token=None):
        tried.append(url)
        return {"machineIdentifier": "abc"} if "192-168" in url or "203-0" in url else None

    assert onboard.reach(SERVER, "t", probe=probe) == ("https://192-168-1-20.plex.direct:32400", False)
    assert tried[0] == onboard.LOCAL_PLEX and tried[1].startswith("https://192-168")


def test_unreachable_plex_says_so():
    with pytest.raises(SetupError, match="couldn't connect"):
        onboard.reach(SERVER, "t", probe=lambda *a, **k: None)


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
    plex = FakePlex([{"title": "Music", "type": "artist"}, {"title": "Audiobooks", "type": "artist"}])
    monkeypatch.setattr(setup_flow, "PlexClient", lambda url, token: plex)
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
    ran = []
    assert "Windows" in autostart.install("win32", tmp_path, run=lambda *a, **k: ran.append(a[0]))
    script = (tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs/Startup/Radio Booth.cmd").read_text()
    assert r'start "Radio Booth" /min "C:\Users\Al\Downloads\booth.exe" run' in script
    menu = tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs"
    shortcuts = [args[-1] for args in ran if args[0] == "powershell"]  # the Start menu lists shortcuts
    assert len(shortcuts) == 2 and str(menu / "Radio Booth setup.lnk") in shortcuts[1]
    assert "$s.Arguments = 'setup'" in shortcuts[1] and "$s.WindowStyle = 7" in shortcuts[0]

    assert "Mac" in autostart.install("darwin", tmp_path, run=lambda *a, **k: ran.append(a[0]))
    plist = (tmp_path / "Library/LaunchAgents/com.radiobooth.engineer.plist").read_text()
    assert "<string>run</string>" in plist and ran[-1][:2] == ["launchctl", "load"]
    assert "<key>ThrottleInterval</key>" in plist  # a Booth that can't start isn't retried every 10 s

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
    script = autostart.shortcut_script(link, [r"C:\Windows\notepad.exe"], "setup", minimized=False)
    autostart.checked(subprocess.run, ["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    assert link.is_file()


def test_a_failed_service_start_is_an_error(tmp_path):
    from types import SimpleNamespace

    def run(args, **k):
        bad = args[:2] == ["launchctl", "load"]
        return SimpleNamespace(returncode=1 if bad else 0, stderr="Load failed: 5: Input/output error\n")

    with pytest.raises(OSError, match="Input/output error"):
        autostart.install("darwin", tmp_path, run=run)


def test_the_app_keeps_its_window_open_on_a_surprise(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))

    def boom(args):
        raise PermissionError("can't write there")

    monkeypatch.setattr(cli, "setup", boom)
    pauses = []
    monkeypatch.setattr("builtins.input", lambda prompt="": pauses.append(prompt) or "")
    assert cli.app([]) == 1
    assert "can't write there" in capsys.readouterr().err and pauses


def test_an_existing_pairing_can_be_replaced(home, monkeypatch):
    tmp_path, plex, codes = home
    answers = iter(["n", "ABCD-2345"])
    out = setup_flow.pair_step(
        {"device_token": "be_old"}, "https://booth.example", "pc", ask=lambda q: next(answers)
    )
    assert out["device_token"] == "be_device" and codes == ["ABCD-2345"]


def test_windows_scripts_read_non_ascii_paths():
    script = autostart.windows_script([r"C:\\Users\\José\\AppData\\Local\\Radio Booth\\RadioBooth.exe"])
    lines = script.split("\r\n")
    assert lines[1] == "chcp 65001 >nul" and "José" in lines[2]


def test_setup_reuses_the_saved_server(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("BOOTH_SERVER", raising=False)
    config.save({"server": "https://staging.example"})
    seen = []
    monkeypatch.setattr(setup_flow, "guided", lambda server, name: seen.append(server) or 0)
    assert cli.main(["setup"]) == 0 and seen == ["https://staging.example"]


def test_start_menu_actions_keep_the_window_open_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    pauses = []
    monkeypatch.setattr("builtins.input", lambda prompt="": pauses.append(prompt) or "")
    assert cli.app(["run"]) == cli.NEEDS_PAIRING  # not set up yet: says so, then waits
    assert pauses and cli.app(["--version"]) == 0 and len(pauses) == 1


@pytest.mark.parametrize(
    "code, answer, keep",
    [(cli.NEEDS_SETUP, "", True), (cli.NEEDS_PAIRING, "", False), (cli.ALREADY_RUNNING, "y", True)],
)
def test_a_double_click_that_needs_setup_offers_it(tmp_path, monkeypatch, code, answer, keep):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    config.save({"device_token": "be_dead", "plex_token": "t", "server": "https://booth.example"})
    monkeypatch.setattr(cli, "run", lambda args: code)
    seen = []
    monkeypatch.setattr(
        setup_flow, "guided", lambda server, name, keep_pairing: seen.append((server, keep_pairing)) or 0
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    assert cli.app([]) == 0
    assert seen == [("https://booth.example", keep)]


def test_already_running_needs_a_yes_to_change_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    config.save({"device_token": "be", "plex_token": "t"})
    monkeypatch.setattr(cli, "run", lambda args: cli.ALREADY_RUNNING)
    monkeypatch.setattr(setup_flow, "guided", lambda *a, **k: pytest.fail("setup without a yes"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert cli.app([]) == cli.ALREADY_RUNNING


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

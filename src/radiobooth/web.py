"""The Booth app: Booth running in the background, with a page in the browser to set it up and see how it's
doing. No terminal window.

The page is served only to this computer: the server listens on 127.0.0.1, which nothing on the network can
reach, and needs no router or firewall change. Other websites open in the same browser can't use it either:
- every request needs the page key (a long random secret in Booth's config file), which the app hands to
  the browser in the link it opens, and the browser keeps as a cookie only this page gets;
- requests must name this page's own address as Host, which defeats DNS rebinding;
- changes must come from this page (Origin) as JSON, which another site's page can't send without asking
  first, and Booth never answers such a question with a yes (no CORS headers).
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from radiobooth import __version__, autostart, config, engine, history, page, update
from radiobooth.link import Link, LinkError
from radiobooth.onboard import SetupError
from radiobooth.websetup import WebSetup, plex_ready

HOST = "127.0.0.1"
PORT = 48231  # the same address each time when it's free, so a page left open finds Booth again
COOKIE = "booth_key"
SHOW_CHOICES = ("minutes", "dj", "voice", "dj_name", "station")  # kept for next time; the prompt isn't
ROSTER_S = 600  # the DJs and voices change only with a new Booth DJ, so the page asks for them now and then


def page_file() -> Path:
    """Where the running app says where its page is, for the next copy that's opened."""
    return config.path().parent / "page.json"


def page_key() -> str:
    key = config.load().get("page_key")
    return key or config.update({"page_key": secrets.token_urlsafe(32)})["page_key"]


def bind(port: int = PORT) -> socket.socket:
    """A listening socket on 127.0.0.1: the usual port, or any free one."""
    for p in (port, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: never share the port with another program
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:  # rebind straight after a restart; still only one listener at a time
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, p))
        except OSError:
            s.close()
            continue
        s.listen(16)
        return s
    raise OSError("Booth couldn't start its page on this computer")


def page_link(path: Path | None = None) -> str | None:
    """The page of the Booth running now, with its key, or None."""
    try:
        data = json.loads((path or page_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = data.get("url") if isinstance(data, dict) else None
    return url if isinstance(url, str) and url.startswith(f"http://{HOST}:") else None


_direct = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)  # never via a proxy: it's this computer


def answering(link: str, timeout: float = 2) -> bool:
    base = link.split("/?", 1)[0]
    try:
        with _direct.open(f"{base}/ping", timeout=timeout) as resp:
            return resp.read() == b"booth"
    except OSError:
        return False


class App:
    """Everything the page shows and does."""

    def __init__(self, name: str, platform: str = sys.platform):
        self.platform = platform
        self.engine = engine.Engine()
        self.setup = WebSetup(self.server, name, on_saved=self._saved)
        self.updater = update.Updater(
            busy=lambda: self.engine.busy,
            restart=self.restart,
            auto=lambda: config.load().get("auto_update", True),
        )
        self.quit = threading.Event()
        self.restarting = False
        self._roster: tuple[float, dict] | None = None
        self._paired = 0  # counts pairings, so a roster from before the latest one isn't kept

    def server(self) -> str:
        from radiobooth.cli import DEFAULT_SERVER

        return os.environ.get("BOOTH_SERVER") or config.load().get("server") or DEFAULT_SERVER

    def _saved(self) -> None:
        self._roster = None  # paired again, maybe with another Radio Booth: ask it for its DJs
        self._paired += 1
        settings = config.load()
        if plex_ready(settings) and settings.get("device_token"):
            if not settings.get("set_up_once"):
                config.update({"set_up_once": True})
                if self.platform in ("win32", "darwin") and not autostart.installed(self.platform):
                    # Recommended, and what testers expect: shows arrive without opening anything.
                    with contextlib.suppress(OSError):
                        self.engine.log(autostart.install(self.platform))
            self.engine.start()

    def restart(self) -> None:
        """After an update: start the new version and stop this one, once any show in hand is in Plex."""
        self.restarting = True
        self.engine.stop(wait=None)
        update.relaunch(self.platform)
        self.quit.set()

    def state(self) -> dict:
        settings = config.load()
        unpaired = self.engine.unpaired
        return {
            "version": __version__,
            "platform": self.platform,
            "plex": {
                "ready": plex_ready(settings),
                "music": settings.get("music_library"),
                "url": settings.get("plex_url"),
                "breaks_dir": settings.get("breaks_dir"),
            },
            "account": {
                "paired": bool(settings.get("device_token")),
                "name": settings.get("name"),
                "account_name": settings.get("account_name"),
                "people": [
                    {"id": p["id"], "name": p["name"], "unpaired": p["id"] in unpaired}
                    for p in config.people(settings)
                ],
            },
            "server": self.server(),
            "setup": self.setup.state(),
            "engine": self.engine.status(),
            "update": self.updater.status() | {"auto": settings.get("auto_update", True)},
            "autostart": {
                "available": self.platform in ("win32", "darwin"),
                "on": autostart.installed(self.platform),
            },
            "restarting": self.restarting,
        }

    def _link(self, settings: dict | None = None, who: str | None = None) -> Link:
        """The link for this computer's own account, or (`who`) for another person sharing it."""
        settings = settings or config.load()
        token = settings.get("device_token")
        if not token:
            raise SetupError("Connect Booth to your account first.")
        if who:
            person = next((p for p in config.people(settings) if p["id"] == who), None)
            if person is None:
                raise SetupError("Booth doesn't make shows for that person any more. Reload this page.")
            token = person["device_token"]
        try:
            # The server it paired with and checks in with, never another one the token would mean nothing to.
            return Link(settings.get("server") or self.server(), token, timeout=30)
        except LinkError as e:
            raise SetupError(str(e)) from None

    def _said(self, e: LinkError, asked: bool = False, who: str | None = None) -> SetupError:
        """What the page says when Booth DJ couldn't take or answer a request (`asked`: for a new show; `who`:
        for another person sharing this Booth)."""
        said = str(e).removeprefix("Booth DJ: ")
        if who and e.status == 401:
            name = next((p["name"] for p in config.people(config.load()) if p["id"] == who), "Their")
            return SetupError(
                f"{name}'s Booth account no longer knows this computer. Add them again in Settings with a new"
                " code from their phone."
            )
        if asked and (e.network or e.status is None or e.status >= 500):
            # It may have got there and the answer was lost or garbled: don't ask for the same show twice.
            return SetupError("Radio Booth didn't answer. Check the list below before asking again.")
        if e.network:
            return SetupError("Booth can't reach Radio Booth right now. Is this computer online?")
        if e.status is None:
            return SetupError("Radio Booth sent an answer Booth didn't understand. Try again in a moment.")
        if e.status == 401:
            if self.engine.state != engine.NEEDS_PAIRING:  # check-ins still work, so it's still paired
                return SetupError("Radio Booth can't take shows from this page yet. Ask on your phone.")
            return SetupError("Your Booth account doesn't know this computer. Connect it again in Settings.")
        if said.startswith("HTTP "):  # no message of its own (a 502 from in front of it, say)
            return SetupError("Radio Booth is having trouble right now. Try again in a moment.")
        return SetupError(said)

    def shows(self, who: str | None = None) -> dict:
        """For the page's New show section: the DJs and voices, show time left, and the latest shows, for this
        computer's own account or (`who`) another person sharing it."""
        paired = self._paired  # before the settings: a pairing saved after this makes the roster stale
        settings = config.load()
        link = self._link(settings, who)
        try:
            if not self._roster or time.monotonic() - self._roster[0] > ROSTER_S:
                me = link.get("/v0/me")
                roster = me.get("roster")
                if not isinstance(roster, dict) or not roster.get("djs"):
                    raise LinkError("Booth DJ sent no DJs to pick from.")
                if paired == self._paired:
                    self._roster = (time.monotonic(), roster)
                name = me.get("name")
                if not who and isinstance(name, str) and name and name != settings.get("account_name"):
                    with contextlib.suppress(OSError):  # whose Booth this is, for the page's People list
                        config.update({"account_name": name})
            else:
                roster = self._roster[1]
            listed = link.get("/v0/shows")
        except LinkError as e:
            raise self._said(e, who=who) from None
        shows = listed.get("shows")
        return {
            "roster": roster,
            "allowance": listed.get("allowance"),
            "shows": shows[:6] if isinstance(shows, list) else [],
            "choices": settings.get("show_choices") or {},
        }

    def new_show(self, body: dict) -> dict:
        """Ask Booth DJ for a show, as the phone page does. It checks the request and says what's wrong."""
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise SetupError("Say what the show is about.")
        who = body.get("who")
        who = who if isinstance(who, str) and who else None
        link = self._link(who=who)
        if self.engine.state != engine.ON_AIR:
            # A show asked for here is made from this computer's music and delivered here, so it waits for
            # this Booth; asked for while it can't make one, it would hold up the shows asked for after it.
            raise SetupError("Booth isn't on the air right now (see above), so it can't make a show yet.")
        choices = {k: body[k] for k in SHOW_CHOICES if isinstance(body.get(k), str | int)}
        try:
            made = link.ask({"prompt": prompt, **choices})
        except LinkError as e:
            raise self._said(e, asked=True, who=who) from None
        with contextlib.suppress(OSError):  # the show is asked for; not remembering choices is no failure
            config.update({"show_choices": choices})
        return {"show_id": made.get("show_id")}

    def _account_name(self, link: Link) -> str | None:
        try:
            name = link.get("/v0/me").get("name")
        except LinkError:
            return None
        return (name.strip()[:60] or None) if isinstance(name, str) else None

    def add_person(self, code: str) -> dict:
        """Connect another person's Booth account to this computer too, with a pairing code from their phone.
        Their shows are made from the same music and go into the same Plex, with their name before each
        playlist's title."""
        code = code.strip()
        if not code:
            raise SetupError("Type the code from their phone first.")
        settings = config.load()
        main = self._link(settings)
        try:
            # Under a name of its own, so a code from this computer's own account by mistake can't take this
            # computer's unfinished shows over (Radio Booth hands those to a computer paired again under the
            # same name), while the same person added again does get theirs back.
            computer = settings.get("name") or self.setup._name
            token = Link(main.server).redeem(code, f"{computer} (shared)")
        except LinkError as e:
            if e.status == 404:
                raise SetupError(
                    "That code didn't work. Codes last 10 minutes and work once; get a new one and try again."
                ) from None
            raise self._said(e) from None
        name = self._account_name(Link(main.server, token, timeout=30))
        if not name:
            raise SetupError(
                "Radio Booth took the code but didn't say whose account it is. Get a new code and try again."
            )
        own = self._account_name(main)
        if own and own != settings.get("account_name"):
            config.update({"account_name": own})
        if name == (own or settings.get("account_name")):
            # Most likely a code from the account Booth already makes shows for. Radio Booth has no account id
            # to tell, so nothing changes rather than risk mixing two accounts up.
            raise SetupError(
                f"That code is from an account named {name}, like the one Booth already makes shows for. To"
                " add someone else, get the code on their phone while they're signed in to their own account."
                " (Booth tells accounts apart by name, so two with the same name can't share it.)"
            )
        unpaired = self.engine.unpaired

        def change(people: list[dict]) -> list[dict]:
            again = next((p for p in people if p["name"] == name and p["id"] in unpaired), None)
            if again:  # them again, after their Booth account forgot this computer: their history carries on
                return [p | {"device_token": token} if p is again else p for p in people]
            person = {
                "id": config.new_person_id(),
                "device_token": token,
                "name": name,
                "server": main.server,
            }
            return [*people, person]

        config.change_people(change)
        self.engine.start()
        return {"name": name}

    def remove_person(self, who: str) -> None:
        if not any(p["id"] == who for p in config.people(config.load())):
            raise SetupError("Booth doesn't make shows for that person any more.")
        config.change_people(lambda people: [p for p in people if p["id"] != who])
        with contextlib.suppress(OSError):  # their show history goes with them
            history.path(who).unlink(missing_ok=True)
        self.engine.start()

    def act(self, action: str, body: dict) -> dict:
        """What a button on the page asks for. SetupError: something to tell the person."""
        if action == "plex":
            return {"url": self.setup.start_plex()}
        if action == "cancel":
            self.setup.cancel()
        elif action == "choose":
            self.setup.choose(int(body.get("index", -1)))
        elif action == "folder":
            self.setup.use_folder(str(body.get("path", "")))
        elif action == "new_show":
            return self.new_show(body)
        elif action == "add_person":
            return self.add_person(str(body.get("code", "")))
        elif action == "remove_person":
            self.remove_person(str(body.get("id", "")))
        elif action == "pair":
            return {"name": self.setup.pair(str(body.get("code", "")))}
        elif action == "autostart":
            change = autostart.install if body.get("on") else autostart.remove
            try:
                said = change(self.platform)
            except OSError as e:
                raise SetupError(f"Couldn't change that ({e}).") from None
            return {"said": said}
        elif action == "auto_update":
            config.update({"auto_update": bool(body.get("on"))})
        elif action == "check_update":
            self.updater.check_now()
        elif action == "install_update":
            self.updater.install_now()
        elif action == "restart_engine":
            self.engine.start()
        elif action == "quit":
            threading.Timer(0.5, self.quit.set).start()  # answer the page first
        else:
            raise SetupError("Booth doesn't know that button.")
        return {}


def handler(app: App, key: str, origins: set[str]) -> type[BaseHTTPRequestHandler]:
    hosts = {o.removeprefix("http://") for o in origins}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Booth"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002 - the page's requests aren't worth a log line
            pass

        def _send(self, status: int, body: bytes, kind: str, headers: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:;"
                " connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in hosts

        def _key_ok(self) -> bool:
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE and hmac.compare_digest(value.encode(), key.encode()):
                    return True
            return False

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(HTTPStatus.MISDIRECTED_REQUEST, b"", "text/plain")
            path, _, query = self.path.partition("?")
            if path == "/ping":  # lets a second copy of the app know this one is here; says nothing else
                return self._send(200, b"booth", "text/plain")
            if path == "/" and query.startswith("k="):
                given = query[2:].split("&", 1)[0]
                if hmac.compare_digest(given.encode(), key.encode()):
                    cookie = f"{COOKIE}={key}; HttpOnly; SameSite=Strict; Path=/"
                    return self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
            if not self._key_ok():
                return self._send(403, page.LOCKED.encode(), "text/html; charset=utf-8")
            if path == "/":
                return self._send(200, page.HTML.encode(), "text/html; charset=utf-8")
            if path == "/page.js":
                return self._send(200, page.SCRIPT.encode(), "text/javascript; charset=utf-8")
            if path == "/api/state":
                return self._json(200, app.state())
            if path == "/api/shows":
                who = next((v for k, _, v in (p.partition("=") for p in query.split("&")) if k == "who"), "")
                try:
                    return self._json(200, app.shows(who or None))
                except SetupError as e:
                    return self._json(422, {"error": str(e)})
                except Exception as e:  # noqa: BLE001 - say what on the page
                    return self._json(500, {"error": f"Something went wrong: {e}"})
            return self._send(404, b"", "text/plain")

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or self.headers.get("Origin") not in origins or not self._key_ok():
                return self._json(403, {"error": "Not from Booth's page."})
            if self.headers.get_content_type() != "application/json" or not self.path.startswith("/api/"):
                return self._json(400, {"error": "Not a Booth request."})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "Not a Booth request."})
            try:
                return self._json(200, app.act(self.path.removeprefix("/api/"), body))
            except SetupError as e:
                return self._json(422, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - say what on the page
                return self._json(500, {"error": f"Something went wrong: {e}"})

    return Handler


def serve(app: App, sock: socket.socket, key: str) -> tuple[ThreadingHTTPServer, str]:
    """Start the page on `sock`; returns the server and the link (with the key) that opens it."""
    port = sock.getsockname()[1]
    origins = {f"http://{HOST}:{port}", f"http://localhost:{port}"}
    httpd = ThreadingHTTPServer((HOST, port), handler(app, key, origins), bind_and_activate=False)
    httpd.socket.close()
    httpd.socket = sock
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="booth-page", daemon=True).start()
    return httpd, f"http://{HOST}:{port}/?k={key}"


def write_page_file(link: str) -> None:
    p = page_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # it holds the key: yours only
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"url": link, "pid": os.getpid()}, f)


def notice(text: str, platform: str = sys.platform) -> None:
    """Tell the person something when there's no page to show it on. The Windows app has no console, so a
    message box; elsewhere, the terminal (or the log)."""
    print(text, file=sys.stderr)
    if platform == "win32" and getattr(sys, "frozen", False):
        with contextlib.suppress(AttributeError, OSError):
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "Radio Booth", 0x40)  # MB_ICONINFORMATION


def open_running(open_browser: Callable[[str], bool], wait_s: float = 15) -> bool:
    """Open the page of the Booth already running here, waiting a little for it to come up."""
    deadline = time.monotonic() + wait_s
    while True:
        link = page_link()
        if link and answering(link):
            open_browser(link)
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)


def main(
    name: str,
    background: bool = False,
    wait: bool = False,
    open_browser: Callable[[str], bool] = webbrowser.open,
    lock_path: Path | None = None,
) -> int:
    """`booth app`: be the one Booth on this computer, with its page; or open the page of the one running."""
    from radiobooth.cli import single_instance

    lock_path = lock_path or config.path().parent / "run.lock"
    lock = single_instance(lock_path)
    deadline = time.monotonic() + (30 if wait else 0)
    while lock is None and time.monotonic() < deadline:  # an update: the old version is on its way out
        time.sleep(0.5)
        lock = single_instance(lock_path)
    if lock is None:
        if background or open_running(open_browser):
            return 0
        notice(
            "Booth is already running on this computer, in an older version or as `booth run`, so it has no"
            " page to show. Close that Booth (its window, or `booth run`), then open Radio Booth again."
        )
        return 5

    if getattr(sys, "frozen", False) and autostart.outdated():
        with contextlib.suppress(OSError):  # an older version's sign-in item: start as the app from now on
            autostart.install()
    if getattr(sys, "frozen", False) and sys.platform == "win32":

        def start_menu():
            with contextlib.suppress(OSError):
                autostart.start_menu()

        threading.Thread(target=start_menu, name="booth-start-menu", daemon=True).start()
    app = App(name)
    key = page_key()
    httpd, link = serve(app, bind(), key)
    write_page_file(link)
    settings = config.load()
    if plex_ready(settings) and settings.get("device_token"):
        app.engine.start()
    if app.updater.can_install:  # the apps only: the `booth` command never asks GitHub by itself
        app.updater.start()
    if not background:
        open_browser(link)
    try:
        while not app.quit.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    app.engine.stop()
    httpd.shutdown()
    httpd.server_close()
    with contextlib.suppress(OSError):
        page_file().unlink()
    lock.close()
    return 0

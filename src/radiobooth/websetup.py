"""Setup on Booth's page: the same steps as `booth setup` (see setup_flow), as buttons and lists.

Each step runs in the background and the page asks for `state()` every second or two. Plex first: sign in
on Plex's own page, pick the server and music library if there's a choice, and the breaks library is found or
made. Then the pairing code from the phone. What's done is saved straight away, like `booth setup`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from radiobooth import config, onboard
from radiobooth.link import Link, LinkError
from radiobooth.onboard import SetupError
from radiobooth.sources.plex import PlexClient, PlexError, music_sections

PLEX_KEYS = ("plex_url", "plex_token", "music_library", "breaks_library", "breaks_dir")


def plex_ready(settings: dict) -> bool:
    return all(settings.get(k) for k in PLEX_KEYS)


class WebSetup:
    """One person setting up at a time; a new start replaces whatever was half done."""

    def __init__(
        self,
        server: Callable[[], str],
        name: str,
        on_saved: Callable[[], None],
    ):
        self._booth, self._name, self._on_saved, self._ob = server, name, on_saved, onboard
        self._lock = threading.Lock()
        self._run_id = 0
        self.reset()

    def reset(self) -> None:
        self._run_id += 1
        self.step = "idle"  # idle | plex_wait | working | server | library | folder | done
        self.error = ""
        self.sign_in_url = ""
        self.choices: list[str] = []
        self.folder_hint = ""
        self._token = self._client_id = ""
        self._servers: list[dict] = []
        self._server: dict | None = None
        self._url, self._here, self._plex = "", False, None
        self._sections: list[dict] = []
        self._breaks: dict | None = None
        self._chosen: dict | None = None

    def state(self) -> dict:
        return {
            "step": self.step,
            "error": self.error,
            "sign_in_url": self.sign_in_url,
            "choices": self.choices,
            "folder_hint": self.folder_hint,
        }

    def _background(self, work: Callable[[], None]) -> None:
        run_id = self._run_id

        def go():
            try:
                work()
            except SetupError as e:
                if run_id == self._run_id:
                    self.step, self.error = "idle", str(e)
            except Exception as e:  # noqa: BLE001 - say what, so the page doesn't hang
                if run_id == self._run_id:
                    self.step, self.error = "idle", f"Something went wrong: {e}"

        threading.Thread(target=go, name="booth-setup", daemon=True).start()

    # Plex

    def start_plex(self) -> str:
        """Start a Plex sign-in; returns the Plex page for the person to sign in on."""
        with self._lock:
            self.reset()
            settings = config.load()
            client_id = settings.get("plex_client_id") or self._ob.new_client_id()
            if not settings.get("plex_client_id"):
                config.save(config.load() | {"plex_client_id": client_id})
            self._client_id = client_id
            pin, url = self._ob.start_sign_in(client_id)
            self.step, self.sign_in_url = "plex_wait", url
            run_id = self._run_id

            def wait():
                token = self._ob.wait_sign_in(client_id, pin, cancelled=lambda: run_id != self._run_id)
                self._signed_in(token)

            self._background(wait)
            return url

    def _signed_in(self, token: str) -> None:
        self.step = "working"
        self._token = token
        servers = self._ob.owned_servers(token, self._client_id)
        if not servers:
            raise SetupError(
                "That Plex account has no server of its own. Sign in with the account that owns your Plex"
                " server."
            )
        self._servers = servers
        if len(servers) == 1:
            self._use_server(servers[0])
        else:
            self.choices = [s.get("name", "?") for s in servers]
            self.step = "server"

    def choose(self, index: int) -> None:
        """Pick from `choices` at the server or library step."""
        if not 0 <= index < len(self.choices):
            raise SetupError("That isn't one of the choices.")
        step, self.choices, self.error = self.step, [], ""
        if step == "server":
            self.step = "working"
            self._background(lambda: self._use_server(self._servers[index]))
        elif step == "library":
            self.step = "working"
            self._background(lambda: self._use_library(self._music[index]))
        else:
            raise SetupError("There's nothing to choose right now.")

    def _use_server(self, server: dict) -> None:
        self._server = server
        url, here = self._ob.reach(server, self._token)
        token = server.get("accessToken") or self._token
        self._url, self._here, self._token = url, here, token
        self._plex = PlexClient(url, token)
        try:
            sections = music_sections(self._plex)
        except PlexError as e:
            raise SetupError(f"Couldn't read the libraries on that Plex server ({e}).") from None
        self._breaks = next((s for s in sections if s.get("title") == self._ob.BREAKS_LIBRARY), None)
        self._music = [s for s in sections if s is not self._breaks]
        if not self._music:
            raise SetupError("That Plex server has no music library. Add your music to Plex, then try again.")
        if len(self._music) == 1:
            self._use_library(self._music[0])
        else:
            self.choices = [s.get("title", "?") for s in self._music]
            self.step = "library"

    def _use_library(self, chosen: dict) -> None:
        self._chosen = chosen
        ob, breaks = self._ob, self._breaks
        if breaks is None and self._here:
            folder = ob.default_breaks_dir(ob.library_folders(self._plex), ob.plex_user_id())
            ob.make_breaks_library(self._plex, folder)
            self._save_plex(str(folder))
        elif self._here and breaks is not None and (path := ob.section_path(breaks)):
            try:  # its folder may have been tidied away; Plex on this computer sees it again once it's back
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise SetupError(
                    f"Your {ob.BREAKS_LIBRARY!r} Plex library uses {path}, and Booth can't make that folder"
                    f" ({e.strerror or e}). In Plex, point the library at a folder that exists, then try"
                    " again."
                ) from None
            self._save_plex(path)
        elif breaks is None:
            raise SetupError(
                f"Your Plex server {self._server.get('name')!r} runs on another computer. The easiest way to"
                " use Booth is to run it on that computer instead. To use it here, make a folder on the Plex"
                f" computer, add a Music library named {ob.BREAKS_LIBRARY!r} for it in Plex, share the folder"
                " so this computer can open it, then try again."
            )
        else:
            self.folder_hint = (
                f"Your Plex server {self._server.get('name')!r} runs on another computer, and its"
                f" {ob.BREAKS_LIBRARY!r} library uses the folder {ob.section_path(breaks)!r} there. Where is"
                " that same folder from this computer?"
            )
            self.step = "folder"

    def use_folder(self, path: str) -> None:
        if self.step != "folder":
            raise SetupError("Booth isn't asking for a folder right now.")
        path = path.strip().strip('"')
        if not path or not Path(path).is_dir():
            raise SetupError(
                "That folder isn't reachable from here. Check it's shared and connected, then try again."
            )
        self._save_plex(path)

    def _save_plex(self, breaks_dir: str) -> None:
        config.save(
            config.load()
            | {
                "plex_url": self._url,
                "plex_token": self._token,
                "music_library": self._chosen.get("title"),
                "breaks_library": self._ob.BREAKS_LIBRARY,
                "breaks_dir": breaks_dir,
            }
        )
        self.step, self.error, self.choices = "done", "", []
        self._on_saved()

    # Booth account

    def pair(self, code: str) -> str:
        """Connect this computer to the Booth account with the code from the phone; returns its name."""
        code = code.strip()
        if not code:
            raise SetupError("Type the code from your phone first.")
        server = self._booth()
        try:
            token = Link(server).redeem(code, self._name)
        except LinkError as e:
            if e.status == 404:
                raise SetupError(
                    "That code didn't work. Codes last 10 minutes and work once; get a new one and try again."
                ) from None
            raise SetupError(str(e)) from None
        config.save(config.load() | {"server": server, "device_token": token, "name": self._name})
        self._on_saved()
        return self._name

"""Guided setup for people who don't use a terminal: `booth setup`, or double-clicking the app.

It signs in to Plex in the browser (Plex's own sign-in page; Booth never sees the password), finds the Plex
server, picks the music library, makes a separate library for the DJ breaks when Plex runs on this computer,
pairs with Booth and saves it all in the local config file. Every connection is outbound; nothing listens.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from radiobooth.sources.plex import PlexClient, PlexError, music_sections

PRODUCT = "Radio Booth"
PLEX_TV = "https://plex.tv/api/v2"
LOCAL_PLEX = "http://127.0.0.1:32400"
BREAKS_LIBRARY = "Radio Booth"
SIGN_IN_TIMEOUT = 600  # seconds to wait for the browser sign-in


class SetupError(Exception):
    """Something setup can't get past, in words for the person at the keyboard."""


def breaks_dir_candidates() -> list[Path]:
    """Where the breaks folder may go, best first. Not under Music: a Plex music library often watches
    that whole folder, and would then show the DJ's breaks as songs in the listener's own music."""
    home = Path.home()
    if os.name == "nt":
        data = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif sys.platform == "darwin":
        data = home / "Library" / "Application Support"
    else:
        data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return [home / "Radio Booth", data / "Radio Booth" / "breaks"]


def library_folders(client) -> list[str]:
    """Every folder any Plex library watches."""
    sections = client.get("/library/sections")["MediaContainer"].get("Directory", [])
    return [loc["path"] for s in sections for loc in s.get("Location") or [] if loc.get("path")]


def overlaps(folder: Path, other: str) -> bool:
    """One folder is inside the other (or they're the same), comparing the way this system does."""
    a = os.path.normcase(os.path.abspath(folder))
    b = os.path.normcase(os.path.abspath(other))
    try:
        return os.path.commonpath([a, b]) in (a, b)
    except ValueError:  # different drives or network shares on Windows: they can't overlap
        return False


def default_breaks_dir(watched: list[str]) -> Path:
    """The first candidate folder that no Plex library already watches, and that holds no library's folder."""
    for folder in breaks_dir_candidates():
        if not any(overlaps(folder, w) for w in watched):
            return folder
    raise SetupError(
        "Couldn't find a folder for the DJ's breaks that your Plex libraries don't already use. In Plex,"
        f" add a Music library named {BREAKS_LIBRARY!r} for an empty folder of its own, then run setup again."
    )


def new_client_id() -> str:
    return f"radiobooth-{uuid.uuid4()}"


def plex_tv(method: str, path: str, client_id: str, token: str | None = None, params: dict | None = None):
    """A call to plex.tv's account API."""
    query = urllib.parse.urlencode(params or {})
    url = f"{PLEX_TV}{path}" + (f"?{query}" if query else "")
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Client-Identifier": client_id,
        **({"X-Plex-Token": token} if token else {}),
    }
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except ValueError:  # e.g. a Wi-Fi sign-in page answering instead of plex.tv
        raise SetupError(
            "Plex's sign-in service sent something unexpected. Is this computer online?"
        ) from None
    except urllib.error.HTTPError as e:
        raise SetupError(f"Plex's sign-in service said HTTP {e.code}. Try again in a minute.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SetupError(
            f"Couldn't reach plex.tv ({getattr(e, 'reason', e)}). Is this computer online?"
        ) from None


def sign_in_url(client_id: str, code: str) -> str:
    query = urllib.parse.urlencode({"clientID": client_id, "code": code, "context[device][product]": PRODUCT})
    return f"https://app.plex.tv/auth#?{query}"


def sign_in(
    client_id: str, *, open_browser, say, call=plex_tv, sleep=time.sleep, timeout=SIGN_IN_TIMEOUT
) -> str:
    """Sign in to Plex in the browser; returns the account's Plex token."""
    pin = call("POST", "/pins", client_id, params={"strong": "true"})
    url = sign_in_url(client_id, pin["code"])
    say("Opening Plex in your browser. Sign in there and allow Radio Booth.")
    say(f"If no browser window opens, go to this address:\n  {url}")
    open_browser(url)
    waited, misses = 0, 0
    while waited < timeout:
        sleep(2)
        waited += 2
        try:
            got = call("GET", f"/pins/{pin['id']}", client_id, params={"code": pin["code"]})
        except SetupError:  # a moment offline mustn't lose a sign-in that's nearly done; a minute does
            misses += 1
            if misses >= 30:
                raise
            continue
        misses = 0
        if got and got.get("authToken"):
            return got["authToken"]
    raise SetupError("Plex sign-in wasn't finished in time. Run setup again when you're ready.")


def owned_servers(token: str, client_id: str, call=plex_tv) -> list[dict]:
    found = call("GET", "/resources", client_id, token, {"includeHttps": 1, "includeRelay": 0}) or []
    return [r for r in found if "server" in (r.get("provides") or "") and r.get("owned") in (True, 1, "1")]


def identity(url: str, token: str | None = None, timeout: float = 4) -> dict | None:
    """The Plex server's identity at `url`, or None if nothing answers like Plex."""
    req = urllib.request.Request(
        f"{url.rstrip('/')}/identity",
        headers={"Accept": "application/json", **({"X-Plex-Token": token} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("MediaContainer")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
        return None


def reach(server: dict, token: str, probe: Callable = identity) -> tuple[str, bool]:
    """(address to use, whether Plex runs on this computer). Plex on this computer is reached directly;
    otherwise the first of the server's own addresses that answers, local network first."""
    want = server.get("clientIdentifier")
    here = probe(LOCAL_PLEX)
    if here and here.get("machineIdentifier") == want:
        return LOCAL_PLEX, True
    conns = sorted(server.get("connections") or [], key=lambda c: (not c.get("local"), bool(c.get("relay"))))
    for c in conns:
        uri = c.get("uri")
        found = uri and probe(uri, token)
        if found and found.get("machineIdentifier") == want:
            return uri, False
    raise SetupError(
        f"Found your Plex server {server.get('name')!r} but couldn't connect to it from here. Is it on?"
    )


def section_path(section: dict) -> str | None:
    locations = section.get("Location") or []
    return locations[0].get("path") if locations else None


def make_breaks_library(client: PlexClient, folder: Path, name: str = BREAKS_LIBRARY) -> dict:
    """A music library of its own for the DJ breaks, watching `folder` (on this computer, where Plex is)."""
    folder.mkdir(parents=True, exist_ok=True)
    params = {
        "name": name,
        "type": "artist",
        "agent": "tv.plex.agents.music",
        "scanner": "Plex Music",
        "language": "en-US",
        "location": str(folder),
    }
    try:
        client.request("POST", "/library/sections", params)
    except PlexError as e:
        raise SetupError(
            f"Plex wouldn't add the {name!r} library ({e}). In Plex, add a Music library named {name!r}"
            f" for the folder {folder}, then run setup again."
        ) from None
    for s in music_sections(client):
        if s.get("title") == name:
            return s
    raise SetupError(f"Plex didn't show the new {name!r} library. Run setup again in a minute.")


def choose(question: str, items: list, label: Callable, ask: Callable, say: Callable):
    """One of `items`: the only one, or the one the person picks by number."""
    if len(items) == 1:
        return items[0]
    say(question)
    for i, item in enumerate(items, 1):
        say(f"  {i}. {label(item)}")
    while True:
        answer = ask(f"Type a number (1-{len(items)}): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1]
        say("That isn't one of the numbers.")

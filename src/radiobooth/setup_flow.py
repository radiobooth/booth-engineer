"""`booth setup`: the guided setup, step by step in plain words (the pieces are in onboard.py)."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from radiobooth import autostart, config, onboard
from radiobooth.link import Link, LinkError
from radiobooth.onboard import SetupError
from radiobooth.sources.plex import PlexClient, PlexError, music_sections


def say(msg: str = "") -> None:
    print(msg, flush=True)


def yes(question: str, ask=input) -> bool:
    return ask(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")


def guided(server: str, name: str, *, ask=input, open_browser=webbrowser.open) -> int:
    say("Radio Booth setup\n")
    say("Booth reads the titles and details of your music in Plex to plan shows, and puts each finished")
    say("show into Plex as a playlist. Your music files never leave this computer.\n")
    try:
        settings = plex_step(config.load(), ask=ask, open_browser=open_browser)
        config.save(settings)
        settings = pair_step(settings, server, name, ask=ask)
        config.save(settings)
    except SetupError as e:
        say(f"\n{e}")
        return 1
    except (EOFError, KeyboardInterrupt):
        say("\nSetup stopped. Run it again any time; what's done so far is kept.")
        return 1
    say("\nAll set.")
    background = False
    if yes("Start Booth automatically when you sign in to this computer? (Recommended)", ask):
        try:
            say(autostart.install())
            background = sys.platform != "win32"  # Windows starts it at the next sign-in
        except OSError as e:
            say(f"Couldn't set that up ({e}). You can start Booth yourself instead.")
    say("\nNow ask for a show on your phone. It shows up in Plex as a playlist a few minutes later.")
    if background:
        return 0
    say("Booth is running in this window. Leave it open; close it to stop Booth.\n")
    from radiobooth.cli import build_parser, run

    return run(build_parser().parse_args(["run"]))


def plex_step(settings: dict, *, ask, open_browser) -> dict:
    settings = dict(settings)
    client_id = settings.setdefault("plex_client_id", onboard.new_client_id())

    say("Step 1 of 3: Plex")
    keys = ("plex_url", "plex_token", "music_library", "breaks_library", "breaks_dir")
    ready = all(settings.get(k) for k in keys) and Path(settings["breaks_dir"]).is_dir()
    if (
        ready
        and onboard.identity(settings["plex_url"], settings["plex_token"])
        and yes(f"Plex is already set up (music from {settings['music_library']!r}). Keep it?", ask)
    ):
        say("")
        return settings
    token = onboard.sign_in(client_id, open_browser=open_browser, say=say)
    servers = onboard.owned_servers(token, client_id)
    if not servers:
        raise SetupError(
            "That Plex account has no server of its own. Sign in with the account that owns your Plex server."
        )
    server = onboard.choose(
        "Which Plex server has your music?", servers, lambda s: s.get("name", "?"), ask, say
    )
    url, here = onboard.reach(server, token)
    token = server.get("accessToken") or token
    plex = PlexClient(url, token)
    say(f"Connected to Plex server {server.get('name')!r}.\n")

    say("Step 2 of 3: your music")
    try:
        sections = music_sections(plex)
    except PlexError as e:
        raise SetupError(f"Couldn't read the libraries on that Plex server ({e}).") from None
    breaks = next((s for s in sections if s.get("title") == onboard.BREAKS_LIBRARY), None)
    music = [s for s in sections if s is not breaks]
    if not music:
        raise SetupError(
            "That Plex server has no music library. Add your music to Plex, then run setup again."
        )
    chosen = onboard.choose(
        "Which Plex library is your music in?", music, lambda s: s.get("title", "?"), ask, say
    )
    say(f"Using {chosen.get('title')!r}.")

    if breaks is None and here:
        folder = onboard.default_breaks_dir()
        breaks = onboard.make_breaks_library(plex, folder)
        say(f"Made a Plex library called {onboard.BREAKS_LIBRARY!r} for the DJ's breaks, in {folder}.")
        say("It keeps the DJ out of your own music.")
        breaks_dir = str(folder)
    elif here and breaks is not None and (path := onboard.section_path(breaks)) and Path(path).is_dir():
        breaks_dir = path
    else:
        breaks_dir = remote_breaks_dir(breaks, server.get("name"), ask)
    say("")
    return settings | {
        "plex_url": url,
        "plex_token": token,
        "music_library": chosen.get("title"),
        "breaks_library": onboard.BREAKS_LIBRARY,
        "breaks_dir": breaks_dir,
    }


def remote_breaks_dir(breaks: dict | None, server_name: str | None, ask) -> str:
    """Plex runs on another computer: the breaks folder has to be one both can reach."""
    say(f"\nYour Plex server {server_name!r} runs on another computer. The easiest way to use Booth is to")
    say(
        "run it on that computer instead. To keep going here, Booth needs a shared folder that Plex sees too:"
    )
    if breaks is None:
        say("  1. Make a folder on the Plex computer (or a drive it uses), e.g. 'Radio Booth'.")
        say(f"  2. In Plex, add a Music library named {onboard.BREAKS_LIBRARY!r} for that folder.")
        say("  3. Share that folder so this computer can open it, then run setup again.")
        raise SetupError("Run setup again once the library is there.")
    say(
        f"Your {onboard.BREAKS_LIBRARY!r} Plex library uses {onboard.section_path(breaks)!r}"
        " on that computer."
    )
    while True:
        path = ask("Where is that same folder from this computer? ").strip().strip('"')
        if path and Path(path).is_dir():
            return path
        say("That folder isn't reachable from here. Check that it's shared and connected, then try again.")


def pair_step(settings: dict, server: str, name: str, *, ask) -> dict:
    say("Step 3 of 3: your Booth account")
    if settings.get("device_token") and yes(
        "This computer is already connected to your Booth account. Keep that connection?", ask
    ):
        return settings
    try:
        link = Link(server)
    except LinkError as e:
        raise SetupError(str(e)) from None
    say(f"On your phone, open your Booth page ({link.server}) and tap 'Get a pairing code'.")
    while True:
        code = ask("Type the code here: ").strip()
        if not code:
            continue
        try:
            token = link.redeem(code, name)
        except LinkError as e:
            if e.status == 404:
                say(
                    "That code didn't work. Codes last 10 minutes and work once; get a new one and try again."
                )
                continue
            raise SetupError(str(e)) from None
        say(f"Connected this computer to your Booth account as {name!r}.")
        return settings | {"server": server, "device_token": token, "name": name}

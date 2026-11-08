"""The `booth` command."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sys
import time
from collections import Counter
from pathlib import Path

from radiobooth import __version__

DEFAULT_SERVER = "https://my.radiobooth.fm"
# What `booth run` exits with when only setup can fix it, so the double-clicked app can offer setup.
NEEDS_SETUP, NEEDS_PAIRING, ALREADY_RUNNING = 3, 4, 5

COMMANDS = {
    "setup": "Set up Booth step by step: sign in to Plex, pick your music, connect to your Booth account.",
    "index": "Read your music library and write a catalog file (nothing leaves this machine).",
    "deliver": "Put a finished show's breaks where your music server sees them and build the playlist.",
    "pair": "Connect this machine to your Radio Booth account with a pairing code.",
}
COMMANDS["run"] = (
    "Stay connected to Booth DJ: send the catalog when you ask for a show, deliver it when ready."
)
COMMANDS["app"] = (
    "Run Booth with its page in your browser (setup, status, settings), or open the page of the Booth"
    " already running here."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="booth", description="Booth Engineer for Radio Booth.")
    parser.add_argument("--version", action="version", version=f"booth {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name == "index":
            p.add_argument("-o", "--output", default="catalog.json", help="where to write the catalog")
            p.add_argument(
                "--library",
                default=os.environ.get("BOOTH_MUSIC_LIBRARY") or None,
                help="Plex music library, if the server has more than one (default $BOOTH_MUSIC_LIBRARY)",
            )
        if name == "deliver":
            p.add_argument("show", help="show folder from Booth DJ (with show.json and breaks/)")
            p.add_argument("--library", help="Plex library for breaks (default $BOOTH_BREAKS_LIBRARY)")
            p.add_argument(
                "--dest", help="that library's folder as seen from here (default $BOOTH_BREAKS_DIR)"
            )
        if name == "pair":
            p.add_argument(
                "code", nargs="?", help="the code from the Booth page on your phone (asked for if left out)"
            )
            p.add_argument("--server", help="Booth DJ address (default $BOOTH_SERVER, then the saved one)")
            p.add_argument("--name", default=socket.gethostname(), help="what to call this machine")
        if name == "setup":
            p.add_argument("--server", help=argparse.SUPPRESS)
            p.add_argument("--name", default=socket.gethostname(), help="what to call this machine")
        if name == "run":
            p.add_argument(
                "--library",
                default=os.environ.get("BOOTH_MUSIC_LIBRARY") or None,
                help="Plex music library, if the server has more than one (default $BOOTH_MUSIC_LIBRARY)",
            )
            p.add_argument("--once", action="store_true", help="check in once and exit")
        if name == "app":
            p.add_argument("--background", action="store_true", help="don't open the page in the browser")
            p.add_argument(
                "--wait", action="store_true", help=argparse.SUPPRESS
            )  # restarting after an update
            p.add_argument("--name", default=socket.gethostname(), help="what to call this machine")
    return parser


def setting(env: str, key: str) -> str | None:
    """A setting from the environment, else from the config file `booth setup` wrote."""
    from radiobooth import config, engine

    return engine.setting(config.load(), env, key)


def plex_login() -> tuple[str | None, str | None]:
    return setting("PLEX_URL", "plex_url"), setting("PLEX_TOKEN", "plex_token")


def coverage(tracks: list[dict]) -> str:
    counts = Counter(k for t in tracks for k in t)
    fields = ["album", "year", "genres", "added_at", "play_count", "rating", "musicbrainz_id"]
    fields += ["last_in_show_at"]
    total = len(tracks) or 1
    return ", ".join(f"{f} {100 * counts[f] // total}%" for f in fields)


def remember(show_dir: Path, log) -> None:
    from radiobooth.engine import remember as note

    note(show_dir, log)


def index(args: argparse.Namespace) -> int:
    from radiobooth import history
    from radiobooth.sources.plex import PlexClient, PlexError, build_catalog

    url, token = plex_login()
    if not (url and token):
        print("booth index: run `booth setup`, or set PLEX_URL and PLEX_TOKEN.", file=sys.stderr)
        return 1
    try:
        exclude = setting("BOOTH_BREAKS_LIBRARY", "breaks_library")
        library = args.library or setting("BOOTH_MUSIC_LIBRARY", "music_library")
        catalog, skipped = build_catalog(PlexClient(url, token), library, exclude=exclude)
        history.annotate(catalog)
    except PlexError as e:
        print(f"booth index: {e}", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tracks = catalog["tracks"]
    print(
        f"Wrote {len(tracks)} tracks from {catalog['source']['library']!r} to {out}"
        f" ({skipped} skipped for missing title, artist or length).",
        file=sys.stderr,
    )
    print(f"Field coverage: {coverage(tracks)}", file=sys.stderr)
    return 0


def delivery_settings(command: str, library: str | None, dest: str | None):
    """(PLEX_URL, PLEX_TOKEN, breaks library, breaks folder), or None after explaining what's missing."""
    url, token = plex_login()
    library = library or setting("BOOTH_BREAKS_LIBRARY", "breaks_library")
    dest = dest or setting("BOOTH_BREAKS_DIR", "breaks_dir")
    pairs = [("PLEX_URL", url), ("PLEX_TOKEN", token), ("BOOTH_BREAKS_LIBRARY", library)]
    missing = [n for n, v in [*pairs, ("BOOTH_BREAKS_DIR", dest)] if not v]
    if missing:
        print(f"booth {command}: missing {', '.join(missing)}. Run `booth setup` first.", file=sys.stderr)
        return None
    if not Path(dest).is_dir():
        print(f"booth {command}: {dest} isn't a folder here (is the share mounted?).", file=sys.stderr)
        return None
    return url, token, library, dest


def deliver(args: argparse.Namespace) -> int:
    from radiobooth.sources.plex import PlexClient, PlexError
    from radiobooth.targets.plex import deliver as deliver_to_plex

    settings = delivery_settings("deliver", args.library, args.dest)
    if settings is None:
        return 1
    url, token, library, dest = settings
    try:
        result = deliver_to_plex(PlexClient(url, token), Path(args.show), library, Path(dest))
    except PlexError as e:
        print(f"booth deliver: {e}", file=sys.stderr)
        return 1
    remember(Path(args.show), lambda msg: print(f"booth deliver: {msg}", file=sys.stderr))
    print(
        f"Playlist {result.title!r} is in Plex: {result.tracks} tracks and {result.breaks} breaks"
        f" (breaks in {result.folder}).",
        file=sys.stderr,
    )
    return 0


def pair(args: argparse.Namespace) -> int:
    from radiobooth import config
    from radiobooth.link import Link, LinkError

    server = args.server or os.environ.get("BOOTH_SERVER") or config.load().get("server") or DEFAULT_SERVER
    try:
        link = Link(server)
    except LinkError as e:
        print(f"booth pair: {e}", file=sys.stderr)
        return 1
    code = args.code
    if not code:
        print(f"On your phone, open {link.server}/ and tap Get a pairing code.", file=sys.stderr)
        try:
            code = input("Pairing code: ")
        except (EOFError, KeyboardInterrupt):
            print("\nbooth pair: no code entered.", file=sys.stderr)
            return 1
    if not code.strip():
        print("booth pair: no code entered.", file=sys.stderr)
        return 1
    try:
        token = link.redeem(code.strip(), args.name)
    except LinkError as e:
        print(f"booth pair: {e}", file=sys.stderr)
        return 1
    saved = config.save({**config.load(), "server": server, "device_token": token, "name": args.name})
    print(f"Paired as {args.name!r}. Settings saved in {saved}. Next: booth run", file=sys.stderr)
    return 0


def run(args: argparse.Namespace) -> int:
    from radiobooth import config, engine
    from radiobooth.link import Link, LinkError
    from radiobooth.link import run as run_link

    settings = config.load()
    if not settings.get("device_token"):
        print("booth run: not paired yet. Run `booth pair` first.", file=sys.stderr)
        return NEEDS_PAIRING
    plex_settings = delivery_settings("run", None, None)
    if plex_settings is None:
        return NEEDS_SETUP

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)

    lock = single_instance(config.path().parent / "run.lock")
    if lock is None:
        print(
            "booth run: Booth is already running on this computer. If you just changed its settings, close"
            " the other Booth window and open Booth again so they take effect.",
            file=sys.stderr,
        )
        return ALREADY_RUNNING
    station = engine.station(settings, log, music=args.library)
    log(f"Connected to {settings['server']} as {settings.get('name', 'this machine')!r}.")
    try:
        run_link(Link(settings["server"], settings["device_token"]), station, once=args.once)
    except LinkError as e:
        hint = " Booth DJ no longer knows this machine: run `booth pair` again." if e.status == 401 else ""
        print(f"booth run: {e}.{hint}", file=sys.stderr)
        return NEEDS_PAIRING if e.status == 401 else 1
    except KeyboardInterrupt:
        return 0
    return 0


def single_instance(path: Path):
    """An open, locked file while this is the only `booth run` here, else None. The lock goes when the
    process does, however it ends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")  # noqa: SIM115 - held for the life of the process
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def setup(args: argparse.Namespace) -> int:
    from radiobooth import config
    from radiobooth.setup_flow import guided

    server = args.server or os.environ.get("BOOTH_SERVER") or config.load().get("server") or DEFAULT_SERVER
    return guided(server, args.name)


def app(args: argparse.Namespace) -> int:
    from radiobooth import web

    return web.main(args.name, background=args.background, wait=args.wait)


def without_console(platform: str = sys.platform) -> None:
    """The Windows app has no console window, so nothing to print to: Booth's messages go to a log file next
    to its config instead (the page shows the latest of them)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from radiobooth import config

    log = config.path().parent / "booth.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.is_file() and log.stat().st_size > 2_000_000:
            os.replace(log, log.with_suffix(".log.1"))
        stream = open(log, "a", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    except OSError:
        stream = open(os.devnull, "w")  # noqa: SIM115
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


MAC_CERTIFICATES = "/etc/ssl/cert.pem"  # the certificate authorities macOS trusts, kept up to date by Apple


def use_system_certificates(platform: str = sys.platform) -> None:
    """Let Booth check HTTPS certificates on a Mac. The Python inside the app looks for trusted certificates
    where its own install on the build machine kept them, a file most Macs don't have, so every HTTPS
    connection, starting with plex.tv, failed with CERTIFICATE_VERIFY_FAILED. Use macOS's own list then."""
    import ssl

    if platform != "darwin" or os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return
    found = ssl.get_default_verify_paths()
    if not (found.cafile or found.capath) and Path(MAC_CERTIFICATES).is_file():
        os.environ["SSL_CERT_FILE"] = MAC_CERTIFICATES


def main(argv: list[str] | None = None) -> int:
    without_console()
    use_system_certificates()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles can't print every title; never crash on one
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    if argv is None and getattr(sys, "frozen", False) and not sys.argv[1:]:
        # The app, double-clicked or opened from the Start menu, Finder, Launchpad or Spotlight.
        from radiobooth import macapp

        if macapp.opened_from_finder([]) and (handed_over := macapp.open_app(sys.executable)) is not None:
            return handed_over
        if (moved := windows_home()) is not None:
            return moved
        return dispatch(["app"])
    return dispatch(argv)


def windows_home(platform: str = sys.platform, popen=None) -> int | None:
    """The Windows app runs from a folder of its own (AppData), so the download can go and updates have one
    place to go to. Opened from anywhere else, it copies itself there and starts that copy. Returns None to
    carry on in this process."""
    if platform != "win32" or not getattr(sys, "frozen", False):
        return None
    import subprocess
    import webbrowser

    from radiobooth import autostart, config, web

    home = autostart.app_home(platform, Path.home())
    if Path(sys.executable).resolve() == home.resolve():
        return None
    lock = single_instance(config.path().parent / "run.lock")
    if lock is None:  # Booth's already running: just open its page
        return 0 if web.open_running(webbrowser.open) else None
    lock.close()
    try:
        target = autostart.keep_app([sys.executable], Path.home(), platform)[0]
    except OSError:
        return None
    (popen or subprocess.Popen)([target], close_fds=True)
    return 0


def dispatch(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "index":
        return index(args)
    return {"app": app, "deliver": deliver, "pair": pair, "run": run, "setup": setup}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

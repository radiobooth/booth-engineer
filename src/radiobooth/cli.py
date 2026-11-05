"""The `booth` command."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from collections import Counter
from pathlib import Path

from radiobooth import __version__

COMMANDS = {
    "index": "Read your music library and write a catalog file (nothing leaves this machine).",
    "deliver": "Put a finished show's breaks where your music server sees them and build the playlist.",
    "pair": "Connect this machine to your Radio Booth account with a pairing code.",
}
COMMANDS["run"] = (
    "Stay connected to Booth DJ: send the catalog when you ask for a show, deliver it when ready."
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
            p.add_argument("--server", help="Booth DJ address (default $BOOTH_SERVER)")
            p.add_argument("--name", default=socket.gethostname(), help="what to call this machine")
        if name == "run":
            p.add_argument(
                "--library",
                default=os.environ.get("BOOTH_MUSIC_LIBRARY") or None,
                help="Plex music library, if the server has more than one (default $BOOTH_MUSIC_LIBRARY)",
            )
            p.add_argument("--once", action="store_true", help="check in once and exit")
    return parser


def coverage(tracks: list[dict]) -> str:
    counts = Counter(k for t in tracks for k in t)
    fields = ["album", "year", "genres", "added_at", "play_count", "rating", "musicbrainz_id"]
    fields += ["last_in_show_at"]
    total = len(tracks) or 1
    return ", ".join(f"{f} {100 * counts[f] // total}%" for f in fields)


def remember(show_dir: Path, log) -> None:
    """Note a delivered show's tracks so later shows skip them. Never fails the delivery."""
    from radiobooth import history

    try:
        history.record_package(json.loads((show_dir / "show.json").read_text(encoding="utf-8")))
    except Exception as e:
        log(f"Couldn't update the show history ({e}); later shows may repeat these tracks.")


def index(args: argparse.Namespace) -> int:
    from radiobooth import history
    from radiobooth.sources.plex import PlexClient, PlexError, build_catalog

    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not (url and token):
        print("booth index: set PLEX_URL and PLEX_TOKEN.", file=sys.stderr)
        return 1
    try:
        exclude = os.environ.get("BOOTH_BREAKS_LIBRARY")
        catalog, skipped = build_catalog(PlexClient(url, token), args.library, exclude=exclude)
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
    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    library = library or os.environ.get("BOOTH_BREAKS_LIBRARY")
    dest = dest or os.environ.get("BOOTH_BREAKS_DIR")
    pairs = [("PLEX_URL", url), ("PLEX_TOKEN", token), ("BOOTH_BREAKS_LIBRARY", library)]
    missing = [n for n, v in [*pairs, ("BOOTH_BREAKS_DIR", dest)] if not v]
    if missing:
        print(f"booth {command}: missing {', '.join(missing)}.", file=sys.stderr)
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

    server = args.server or os.environ.get("BOOTH_SERVER") or config.load().get("server")
    if not server:
        print("booth pair: say which Booth DJ to pair with: --server URL or $BOOTH_SERVER.", file=sys.stderr)
        return 1
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
    from radiobooth import config, history
    from radiobooth.link import Link, LinkError, Station
    from radiobooth.link import run as run_link
    from radiobooth.sources.plex import PlexClient, build_catalog
    from radiobooth.targets.plex import deliver as deliver_to_plex

    settings = config.load()
    if not settings.get("device_token"):
        print("booth run: not paired yet. Run `booth pair` first.", file=sys.stderr)
        return 1
    plex_settings = delivery_settings("run", None, None)
    if plex_settings is None:
        return 1
    url, token, library, dest = plex_settings
    plex = PlexClient(url, token)

    def catalog() -> dict:
        return history.annotate(build_catalog(plex, args.library, exclude=library)[0])

    def deliver_show(show_dir: Path) -> str:
        title = deliver_to_plex(plex, show_dir, library, Path(dest)).title
        remember(show_dir, log)
        return title

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)

    station = Station(catalog=catalog, deliver=deliver_show, log=log)
    log(f"Connected to {settings['server']} as {settings.get('name', 'this machine')!r}.")
    try:
        run_link(Link(settings["server"], settings["device_token"]), station, once=args.once)
    except LinkError as e:
        hint = " Booth DJ no longer knows this machine: run `booth pair` again." if e.status == 401 else ""
        print(f"booth run: {e}.{hint}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "index":
        return index(args)
    return {"deliver": deliver, "pair": pair, "run": run}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

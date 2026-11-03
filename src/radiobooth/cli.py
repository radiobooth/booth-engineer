"""The `booth` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from radiobooth import __version__

COMMANDS = {
    "index": "Read your music library and write a catalog file (nothing leaves this machine).",
    "deliver": "Put a finished show's breaks where your music server sees them and build the playlist.",
    "pair": "Connect this machine to your Radio Booth account with a pairing code.",
}
UNBUILT = {"deliver", "pair"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="booth", description="Booth Engineer for Radio Booth.")
    parser.add_argument("--version", action="version", version=f"booth {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name == "index":
            p.add_argument("-o", "--output", default="catalog.json", help="where to write the catalog")
            p.add_argument("--library", help="Plex music library name, if the server has more than one")
    return parser


def coverage(tracks: list[dict]) -> str:
    counts = Counter(k for t in tracks for k in t)
    fields = ["album", "year", "genres", "added_at", "play_count", "rating", "musicbrainz_id"]
    total = len(tracks) or 1
    return ", ".join(f"{f} {100 * counts[f] // total}%" for f in fields)


def index(args: argparse.Namespace) -> int:
    from radiobooth.sources.plex import PlexClient, PlexError, build_catalog

    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not (url and token):
        print("booth index: set PLEX_URL and PLEX_TOKEN.", file=sys.stderr)
        return 1
    try:
        catalog, skipped = build_catalog(PlexClient(url, token), args.library)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "index":
        return index(args)
    print(f"booth {args.command}: not built yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

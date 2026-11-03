"""The `booth` command."""

from __future__ import annotations

import argparse
import sys

from radiobooth import __version__

COMMANDS = {
    "index": "Read your music library and write a catalog file (nothing leaves this machine).",
    "deliver": "Put a finished show's breaks where your music server sees them and build the playlist.",
    "pair": "Connect this machine to your Radio Booth account with a pairing code.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="booth", description="Booth Engineer for Radio Booth.")
    parser.add_argument("--version", action="version", version=f"booth {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in COMMANDS.items():
        sub.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"booth {args.command}: not built yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

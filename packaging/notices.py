"""Write NOTICES.txt for the packaged apps: what's inside besides Booth Engineer, and its licenses.

Run by the release workflow (python packaging/notices.py [tag or commit] > NOTICES.txt) with the Python the
app is built from, since PyInstaller bundles that Python. LICENSE (the GPL) ships next to it.
"""

import platform
import sys
import sysconfig
from pathlib import Path

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from version_info import COPYRIGHT, SOURCE_URL, version  # noqa: E402


def python_license() -> str:
    """The license text that comes with this Python, wherever its build put it. A release can't ship
    without it, so its absence stops the build."""
    for p in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8")  # a misencoded license stops the build too
    raise SystemExit(f"No LICENSE.txt for Python {platform.python_version()} at {sys.base_prefix}.")


def render(v: str | None = None, ref: str | None = None) -> str:
    """`ref` is the tag or commit the app is built from (the tag v<version> unless given): a build that
    isn't a release names its commit, since no tag holds its code."""
    v = v or version()
    ref = ref or f"v{v}"
    return (
        f"Radio Booth {v}\n{COPYRIGHT}\n\n"
        "Booth is free software: you can redistribute it and/or modify it under the terms of the\n"
        "GNU General Public License, version 3 or (at your option) any later version. It comes with\n"
        "ABSOLUTELY NO WARRANTY. See LICENSE.\n"
        f"Source code for this version: {SOURCE_URL}/tree/{ref}\n\n"
        "This app also contains the following, under their own licenses.\n\n"
        f"== Python {platform.python_version()} ==\n\n"
        + python_license()
        + "\n== PyInstaller bootloader ==\n\nGPL-2.0-or-later with the PyInstaller bootloader exception.\n"
        + f"\n== mutagen {installed_version('mutagen')} ==\n\nReads music files' tags."
        " GPL-2.0-or-later, used here under"
        " GPL-3.0-or-later\n(see LICENSE). Source: https://github.com/quodlibet/mutagen\n"
        + f"\n== PyAV {installed_version('av')} and FFmpeg ==\n\nDecodes and mixes music into one-file shows."
        " PyAV is BSD-3-Clause. It bundles FFmpeg and the\nlibraries FFmpeg is built with (LAME among them),"
        " under the GPL and LGPL.\nSource: https://github.com/PyAV-Org/PyAV and https://github.com/PyAV-Org/pyav-ffmpeg\n"
    )


def installed_version(package: str) -> str:
    """The version bundled: the one installed with the Python the app is built from."""
    from importlib.metadata import version as installed

    return installed(package)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # the same file on Windows as elsewhere
    sys.stdout.write(render(ref=sys.argv[1] if len(sys.argv) > 1 else None))

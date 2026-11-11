"""Write NOTICES.txt for the packaged apps: what's inside besides Booth Engineer, and its licenses.

Run by the release workflow (python packaging/notices.py > NOTICES.txt) with the Python the app is built
from, since PyInstaller bundles that Python. LICENSE (the GPL) ships next to it.
"""

import platform
import sys
import sysconfig
from pathlib import Path

SOURCE = "https://github.com/radiobooth/booth-engineer"
PYTHON_LICENSE_URL = "https://docs.python.org/3/license.html"


def python_license() -> str | None:
    """The license text that comes with this Python, wherever its build put it."""
    for p in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def render() -> str:
    head = (
        "Copyright (C) 2026 Thomas Bohmbach, Jr.\n\n"
        "Radio Booth (Booth Engineer) is free software: you can redistribute it and/or modify it under\n"
        "the terms of the GNU General Public License, version 3 or (at your option) any later version.\n"
        "See LICENSE.\n"
        f"Source code: {SOURCE}\n\n"
        "This app also contains the following, under their own licenses.\n\n"
        f"== Python {platform.python_version()} ==\n\n"
    )
    text = python_license()
    if text is None:
        print(f"warning: no Python LICENSE.txt found; linking {PYTHON_LICENSE_URL}", file=sys.stderr)
        text = f"Python Software Foundation License. Full text: {PYTHON_LICENSE_URL}\n"
    return (
        head
        + text
        + "\n== PyInstaller bootloader ==\n\nGPL-2.0-or-later with the PyInstaller bootloader exception.\n"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # the same file on Windows as elsewhere
    sys.stdout.write(render())

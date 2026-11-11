"""Write NOTICES.txt for the packaged apps: what's inside besides Booth Engineer, and its licenses.

Run by the release workflow (python packaging/notices.py > NOTICES.txt) with the Python the app is built
from, since PyInstaller bundles that Python. LICENSE (the GPL) ships next to it.
"""

import platform
import sys
import sysconfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from version_info import COPYRIGHT, version  # noqa: E402

SOURCE = "https://github.com/radiobooth/booth-engineer"


def python_license() -> str:
    """The license text that comes with this Python, wherever its build put it. A release can't ship
    without it, so its absence stops the build."""
    for p in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    raise SystemExit(f"No LICENSE.txt for Python {platform.python_version()} at {sys.base_prefix}.")


def render(v: str | None = None) -> str:
    v = v or version()
    return (
        f"Radio Booth (Booth Engineer) {v}\n{COPYRIGHT}\n\n"
        "Booth Engineer is free software: you can redistribute it and/or modify it under the terms of the\n"
        "GNU General Public License, version 3 or (at your option) any later version. See LICENSE.\n"
        f"Source code for this version: {SOURCE}/tree/v{v}\n\n"
        "This app also contains the following, under their own licenses.\n\n"
        f"== Python {platform.python_version()} ==\n\n"
        + python_license()
        + "\n== PyInstaller bootloader ==\n\nGPL-2.0-or-later with the PyInstaller bootloader exception.\n"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # the same file on Windows as elsewhere
    sys.stdout.write(render())

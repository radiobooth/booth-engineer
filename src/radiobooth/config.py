"""Local settings for Booth Engineer, kept on this machine only.

The pairing token lives in a JSON file readable only by you (mode 0600; on Windows, your profile
folder's permissions): $BOOTH_CONFIG, or
$XDG_CONFIG_HOME/radiobooth/config.json (normally ~/.config/radiobooth/config.json).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def path() -> Path:
    if explicit := os.environ.get("BOOTH_CONFIG"):
        return Path(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "radiobooth" / "config.json"


def load() -> dict:
    p = path()
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save(settings: dict) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # A fresh, uniquely named file (created 0600 by mkstemp), then an atomic rename over the old one.
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=1)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p

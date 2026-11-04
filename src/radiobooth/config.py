"""Local settings for Booth Engineer, kept on this machine only.

The pairing token lives in a JSON file readable only by you: $BOOTH_CONFIG, or
$XDG_CONFIG_HOME/radiobooth/config.json (normally ~/.config/radiobooth/config.json).
"""

from __future__ import annotations

import json
import os
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
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)
        f.write("\n")
    os.replace(tmp, p)
    return p

"""Local settings for Booth Engineer, kept on this machine only.

The pairing token lives in a JSON file readable only by you (mode 0600; on Windows, your profile
folder's permissions): $BOOTH_CONFIG, or
$XDG_CONFIG_HOME/radiobooth/config.json (normally ~/.config/radiobooth/config.json).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_changing = threading.Lock()

# Booth DJ addresses that have moved. Saved settings follow the move; the pairing token stays valid.
MOVED = {"https://booth-dj-juvsqx4frq-uc.a.run.app": "https://my.radiobooth.fm"}


def path() -> Path:
    if explicit := os.environ.get("BOOTH_CONFIG"):
        return Path(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "radiobooth" / "config.json"


def _patiently(step):
    """`step()`, tried again for a moment on Windows when the file is busy: there a file can't be read while
    it's being replaced, nor replaced while it's open for reading (the page reads settings every second or
    two while a background step saves them)."""
    for wait in (0.01, 0.03, 0.1, 0.3, 1.0):
        try:
            return step()
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(wait)
    return step()


def load() -> dict:
    p = path()
    settings = json.loads(_patiently(lambda: p.read_text(encoding="utf-8"))) if p.is_file() else {}
    if moved := MOVED.get(str(settings.get("server") or "").rstrip("/")):
        settings["server"] = moved
    return settings


def save(settings: dict) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # A fresh, uniquely named file (created 0600 by mkstemp), then an atomic rename over the old one.
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=1)
            f.write("\n")
        _patiently(lambda: os.replace(tmp, p))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def update(changes: dict) -> dict:
    """Change some settings and keep the rest. One change at a time, so two parts of Booth saving at once
    (the page and setup, say) never lose each other's settings."""
    with _changing:
        settings = load() | changes
        save(settings)
        return settings


def plex_client_id() -> str:
    """This install's id for plex.tv (X-Plex-Client-Identifier), made and saved the first time it's needed,
    so plex.tv sees one device, not a new one each call."""
    with _changing:
        settings = load()
        if not settings.get("plex_client_id"):
            settings["plex_client_id"] = f"radiobooth-{uuid.uuid4()}"
            save(settings)
        return settings["plex_client_id"]


def folder_key() -> bytes:
    """This install's secret for folder track ids, made and saved the first time it's needed. Ids are keyed
    hashes of file paths, so the service can't check a guessed path against them."""
    with _changing:
        settings = load()
        if not re.fullmatch(r"[0-9a-f]{64}", str(settings.get("folder_key") or "")):
            settings["folder_key"] = secrets.token_hex(32)
            save(settings)
        return bytes.fromhex(settings["folder_key"])


def _plex_user(value) -> dict | None:
    if isinstance(value, dict) and type(value.get("id")) is int and isinstance(value.get("title"), str):
        return {"id": value["id"], "title": value["title"]}
    return None


def people(settings: dict) -> list[dict]:
    """The other Booth accounts sharing this computer ("Add another person" on Booth's page), each
    {"id", "device_token", "name", "server"}. This computer's own account is `device_token`, as always.
    Only those paired with the Booth DJ this computer checks in with now: a token goes to no other server."""
    found = settings.get("people")
    if not isinstance(found, list):
        return []
    server = str(settings.get("server") or "").rstrip("/")
    return [
        p
        | {
            "name": p.get("name") if isinstance(p.get("name"), str) and p.get("name") else "Guest",
            "plex_user": _plex_user(p.get("plex_user")),
        }
        for p in found
        if isinstance(p, dict)
        and isinstance(p.get("device_token"), str)
        and p["device_token"]
        and isinstance(p.get("id"), str)
        and re.fullmatch(r"p_[a-z0-9]{1,32}", p["id"])
        and str(p.get("server") or "").rstrip("/") == server
    ]


def new_person_id() -> str:
    return f"p_{secrets.token_hex(4)}"


def change_people(change) -> list[dict]:
    """Save `change(people)`'s list of people, with the same one-at-a-time care as `update`."""
    with _changing:
        settings = load()
        settings["people"] = change(people(settings))  # people of another server are dropped
        save(settings)
        return settings["people"]

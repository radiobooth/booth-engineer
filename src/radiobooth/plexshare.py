"""Sharing a person's shows with their own Plex user, when people share this Booth.

Every show is made into a playlist with this computer's Plex sign-in, which has to be the server owner's (only
the owner can add the breaks library and scan it). Plex playlists belong to the account that makes them, so
for another person sharing this Booth, the owner's account then shares the playlist with that person's Plex
user, as "Grant Access" on a playlist does in Plex Web. It shows up for them under Shared Playlists in
Plexamp. These calls go to plex.tv, as setup's sign-in does; nothing goes to Booth DJ.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from radiobooth.onboard import PRODUCT
from radiobooth.sources.plex import PlexError

PLEX_TV = "https://plex.tv"


def _call(method: str, path: str, token: str, client_id: str, body: dict | None = None) -> bytes:
    headers = {
        # plex.tv's older /api/ calls answer in XML (asking those for JSON isn't reliable); /api/v2/ in JSON.
        "Accept": "application/json" if path.startswith("/api/v2/") else "application/xml",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Token": token,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{PLEX_TV}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise PlexError(f"plex.tv said HTTP {e.code} for {method} {path.split('?')[0]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PlexError(f"Couldn't reach plex.tv ({getattr(e, 'reason', e)})") from None


def _xml(raw: bytes) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise PlexError("plex.tv sent something unexpected") from None


def users(token: str, client_id: str) -> list[dict]:
    """The Plex users the owner's account can share with: Plex Home users and friends, as
    [{"id": plex.tv user id, "title": their name in Plex}]."""
    found = []
    for u in _xml(_call("GET", "/api/users", token, client_id)).iter("User"):
        try:
            uid = int(u.get("id", ""))
        except ValueError:
            continue
        title = u.get("title") or u.get("username") or u.get("email") or str(uid)
        found.append({"id": uid, "title": title, "home": u.get("home") == "1"})
    return sorted(found, key=lambda u: (not u["home"], u["title"].lower()))


def sees_library(token: str, client_id: str, machine: str, user_id: int, library: str) -> bool | None:
    """Whether the server shares `library` with that user: True, False, or None when plex.tv doesn't say."""
    root = _xml(_call("GET", f"/api/servers/{machine}/shared_servers", token, client_id))
    for share in root.iter("SharedServer"):
        if share.get("userID") != str(user_id):
            continue
        if share.get("allLibraries") == "1":
            return True
        sections = [s for s in share.iter("Section") if s.get("title") == library]
        return any(s.get("shared") == "1" for s in sections) if sections else False
    return False


def share_playlist(
    token: str, client_id: str, machine: str, playlist_key: str, title: str, user_id: int
) -> None:
    """Share one playlist on this server with a Plex user (Plex Web's "Grant Access")."""
    uri = f"server://{machine}/com.plexapp.plugins.library/playlists/{playlist_key}"
    body = {"invitedId": user_id, "items": [{"uri": uri, "type": "playlist", "title": title}]}
    _call("POST", "/api/v2/shared_items", token, client_id, body)

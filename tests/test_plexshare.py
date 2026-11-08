import json

import pytest

from radiobooth import plexshare
from radiobooth.sources.plex import PlexError

USERS = b"""<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer friendlyName="myPlex" size="3">
  <User id="9" title="pat" username="pat" email="pat@example.com" home="0"><Server name="NASh TV"/></User>
  <User id="3427736" title="evoljennifer" username="" home="1"/>
  <User id="oops" title="broken"/>
</MediaContainer>"""

SHARED = b"""<MediaContainer>
  <SharedServer userID="3427736" allLibraries="0">
    <Section key="4" title="Music" shared="1"/><Section key="7" title="Radio Booth" shared="1"/>
  </SharedServer>
  <SharedServer userID="9" allLibraries="0"><Section key="7" title="Radio Booth" shared="0"/></SharedServer>
  <SharedServer userID="5" allLibraries="1"/>
</MediaContainer>"""


@pytest.fixture
def plextv(monkeypatch):
    calls, answers = [], {}

    def call(method, path, token, client_id, body=None):
        calls.append((method, path, token, client_id, body))
        answer = answers[path.split("?")[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(plexshare, "_call", call)
    return calls, answers


def test_plex_users_home_first(plextv):
    _, answers = plextv
    answers["/api/users"] = USERS
    assert plexshare.users("t", "c") == [
        {"id": 3427736, "title": "evoljennifer", "home": True},
        {"id": 9, "title": "pat", "home": False},
    ]


def test_whether_a_user_sees_the_breaks_library(plextv):
    _, answers = plextv
    answers["/api/servers/m1/shared_servers"] = SHARED
    assert plexshare.sees_library("t", "c", "m1", 3427736, "Radio Booth") is True
    assert plexshare.sees_library("t", "c", "m1", 9, "Radio Booth") is False
    assert plexshare.sees_library("t", "c", "m1", 5, "Radio Booth") is True  # everything shared
    assert plexshare.sees_library("t", "c", "m1", 77, "Radio Booth") is None  # not listed: no guess
    answers["/api/servers/m1/shared_servers"] = b"<html>a Wi-Fi sign-in page"
    with pytest.raises(PlexError):
        plexshare.sees_library("t", "c", "m1", 9, "Radio Booth")


def test_sharing_a_playlist_is_plex_webs_grant_access(plextv):
    calls, answers = plextv
    answers["/api/v2/shared_items"] = b"[]"
    plexshare.share_playlist("owner", "c", "m1", "777", "Jennifer: Rain", 3427736)
    method, path, token, _, body = calls[-1]
    assert (method, path, token) == ("POST", "/api/v2/shared_items", "owner")
    assert body == {
        "invitedId": 3427736,
        "items": [
            {
                "uri": "server://m1/com.plexapp.plugins.library/playlists/777",
                "type": "playlist",
                "title": "Jennifer: Rain",
            }
        ],
    }
    json.dumps(body)


def test_plex_tv_calls_ask_for_the_right_format(monkeypatch):
    seen = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("Accept"), req.get_header("Content-type"), req.data))
        return Resp()

    monkeypatch.setattr(plexshare.urllib.request, "urlopen", urlopen)
    plexshare._call("GET", "/api/users", "t", "c")
    plexshare._call("POST", "/api/v2/shared_items", "t", "c", {"a": 1})
    assert seen == [
        ("https://plex.tv/api/users", "application/xml", None, None),
        ("https://plex.tv/api/v2/shared_items", "application/json", "application/json", b'{"a": 1}'),
    ]

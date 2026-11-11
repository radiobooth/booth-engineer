"""Read one music file's tags faithfully, for the folder source.

Each format is read through mutagen's own classes (not the simplified "easy" views), so lists stay lists
and nothing gets flattened. Tags are read, never written: files are opened read-only. Every format's tags
go into the same plain shape first (`Bag`: tag name -> values), and one place turns that into catalog
fields, so MP3, FLAC, Ogg, MP4 and WMA follow the same rules.

The rules (see the design for #29, "Metadata respect"):
- Spelling is the listener's: text is sent as tagged, only Unicode-normalised (NFC) and trimmed.
- Multiple values are real values. A name is never split on "/", ";" or "&" by guessing ("AC/DC" is one
  band); only where the format itself holds several values (ID3v2.4 lists, repeated Vorbis fields, the
  ARTISTS tag MusicBrainz Picard writes).
- The best field wins: the audio stream's own length, never a length tag; an original release date when
  one is tagged.
- Missing stays missing: no guessed years or genres. Ratings and add dates aren't read (not in v1).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, Encoding
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

# What the folder source reads. Other audio files are counted in the tag report by type.
FORMATS = (MP3, FLAC, OggVorbis, OggOpus, MP4, ASF, WAVE, AIFF)
# Not .m4b (audiobooks) or .mp4 (mostly video): an hours-long track doesn't belong in a show.
EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".wma", ".wav", ".aif", ".aiff"}
OTHER_AUDIO = {
    ".aac", ".ac3", ".alac", ".ape", ".dff", ".dsf", ".m4p", ".mka", ".mp2", ".mpc", ".ra", ".shn", ".spx",
    ".tak", ".tta", ".wv",
}  # fmt: skip
YEARS = range(1800, 2201)  # the catalog schema's range
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

Bag = dict[str, list[str]]


class Unreadable(Exception):
    """The file isn't a format Booth reads, or its audio can't be read."""


@dataclass
class Tags:
    fields: dict  # catalog track fields, without id
    lossless: bool = False
    bitrate: int = 0  # bits per second; lossless files sort first anyway
    release_id: str | None = None  # MusicBrainz release, for spotting copies of one album
    repaired: bool = False  # text that was mis-decoded UTF-8 ("BjÃ¶rk") was put right
    garbled: bool = False  # text that looks mis-encoded but couldn't be put right safely
    seen: set[str] = field(default_factory=set)  # which tags were there, for the coverage report


def text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def values(items) -> list[str]:
    """Clean, non-empty, each once (whatever its case), in tagged order."""
    out: list[str] = []
    seen: set[str] = set()
    for v in items:
        v = text(str(v)).strip("\x00").strip()
        if v and v.casefold() not in seen:
            out.append(v)
            seen.add(v.casefold())
    return out


def fix_latin1(value: str) -> tuple[str, bool, bool]:
    """(text, repaired, garbled) for an ID3 Latin-1 string. Tag editors sometimes store UTF-8 bytes in a
    frame marked Latin-1, which reads back as "BjÃ¶rk". Put right only when the bytes are valid UTF-8 and
    the result reads as text; anything else stays as tagged."""
    if value.isascii():
        return value, False, False
    try:
        fixed = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Plain Latin-1 ("Björk") lands here and is fine. Only Ã/Â pairs suggest damage.
        return value, False, bool(re.search(r"[ÃÂ][\x80-\xbf]", value))
    if fixed == value or any(unicodedata.category(c) == "Cc" for c in fixed):
        return value, False, False
    return fixed, True, False


# ---- each format to a Bag ----------------------------------------------------------------------------

_ID3_TEXT = {
    "TIT2": "title",
    "TPE1": "artist",
    "TPE2": "albumartist",
    "TALB": "album",
    "TRCK": "tracknumber",
    "TPOS": "discnumber",
    "TDRC": "date",
    "TDOR": "originaldate",
    "TCOM": "composer",
    "TPUB": "label",
    "TCMP": "compilation",
}
_TXXX = {
    "ARTISTS": "artists",
    "ORIGINALYEAR": "originaldate",
    "ORIGINALDATE": "originaldate",
    "LABEL": "label",
    "MUSICBRAINZ RELEASE GROUP ID": "mb_releasegroup",
    "MUSICBRAINZ ARTIST ID": "mb_artist",
    "MUSICBRAINZ ALBUM ID": "mb_release",
    "FMPS_PLAYCOUNT": "playcount",
}


def _id3(tags: ID3, out: Tags) -> Bag:
    bag: Bag = {}

    def add(key: str, items, latin1: bool = False) -> None:
        got = []
        for v in items:
            v = str(v)
            if latin1:
                v, repaired, garbled = fix_latin1(v)
                out.repaired |= repaired
                out.garbled |= garbled
            got.append(v)
        bag.setdefault(key, []).extend(got)

    for frame in tags.values():
        fid = frame.FrameID
        latin1 = getattr(frame, "encoding", None) == Encoding.LATIN1
        if fid == "TCON":
            add("genre", frame.genres, latin1)  # "(17)" and other ID3v1 numbers become names
        elif fid in _ID3_TEXT:
            add(_ID3_TEXT[fid], frame.text, latin1)
        elif fid == "TXXX" and (key := _TXXX.get(frame.desc.upper())):
            add(key, frame.text, latin1)
        elif fid == "UFID" and frame.owner == "http://musicbrainz.org":
            add("mb_recording", [frame.data.decode("ascii", "replace")])
        elif fid == "PCNT":
            add("playcount", [str(frame.count)])
    return bag


_VORBIS = {
    "TITLE": "title",
    "ARTIST": "artist",
    "ARTISTS": "artists",
    "ALBUMARTIST": "albumartist",
    "ALBUM ARTIST": "albumartist",
    "ALBUM": "album",
    "TRACKNUMBER": "tracknumber",
    "DISCNUMBER": "discnumber",
    "DATE": "date",
    "ORIGINALDATE": "originaldate",
    "ORIGINALYEAR": "originaldate",
    "GENRE": "genre",
    "COMPOSER": "composer",
    "LABEL": "label",
    "ORGANIZATION": "label",
    "PUBLISHER": "label",
    "COMPILATION": "compilation",
    "MUSICBRAINZ_TRACKID": "mb_recording",
    "MUSICBRAINZ_RELEASEGROUPID": "mb_releasegroup",
    "MUSICBRAINZ_ARTISTID": "mb_artist",
    "MUSICBRAINZ_ALBUMID": "mb_release",
    "FMPS_PLAYCOUNT": "playcount",
}


def _vorbis(tags) -> Bag:
    bag: Bag = {}
    for key, value in tags:  # repeated fields are several values
        if name := _VORBIS.get(key.upper()):
            bag.setdefault(name, []).append(value)
    return bag


_MP4 = {
    "©nam": "title",
    "©ART": "artist",
    "aART": "albumartist",
    "©alb": "album",
    "©day": "date",
    "©gen": "genre",
    "©wrt": "composer",
}
_MP4_FREEFORM = {
    "ARTISTS": "artists",
    "LABEL": "label",
    "ORIGINALDATE": "originaldate",
    "ORIGINALYEAR": "originaldate",
    "MUSICBRAINZ TRACK ID": "mb_recording",
    "MUSICBRAINZ RELEASE GROUP ID": "mb_releasegroup",
    "MUSICBRAINZ ARTIST ID": "mb_artist",
    "MUSICBRAINZ ALBUM ID": "mb_release",
}


def _mp4(tags) -> Bag:
    bag: Bag = {}
    for key, items in tags.items():
        if name := _MP4.get(key):
            bag.setdefault(name, []).extend(str(v) for v in items)
        elif key in ("trkn", "disk") and items and isinstance(items[0], tuple):
            bag["tracknumber" if key == "trkn" else "discnumber"] = [str(items[0][0])]
        elif key == "cpil":
            bag["compilation"] = ["1" if items else "0"]
        elif key.startswith("----:") and (name := _MP4_FREEFORM.get(key.rsplit(":", 1)[-1].upper())):
            bag.setdefault(name, []).extend(bytes(v).decode("utf-8", "replace") for v in items)
    return bag


_ASF = {
    "Title": "title",
    "Author": "artist",
    "WM/ARTISTS": "artists",
    "WM/AlbumArtist": "albumartist",
    "WM/AlbumTitle": "album",
    "WM/TrackNumber": "tracknumber",
    "WM/PartOfSet": "discnumber",
    "WM/Year": "date",
    "WM/OriginalReleaseYear": "originaldate",
    "WM/OriginalReleaseTime": "originaldate",
    "WM/Genre": "genre",
    "WM/Composer": "composer",
    "WM/Publisher": "label",
    "WM/IsCompilation": "compilation",
    "MusicBrainz/Track Id": "mb_recording",
    "MusicBrainz/Release Group Id": "mb_releasegroup",
    "MusicBrainz/Artist Id": "mb_artist",
    "MusicBrainz/Album Id": "mb_release",
}


def _asf(tags) -> Bag:
    bag: Bag = {}
    for key, items in tags.items():
        if name := _ASF.get(key):
            for v in items:
                value = v.value
                bag.setdefault(name, []).append(
                    ("1" if value else "0") if isinstance(value, bool) else str(value)
                )
    return bag


# ---- a Bag to catalog fields -------------------------------------------------------------------------


def _year(items: list[str]) -> int | None:
    for v in items:
        if (m := re.match(r"\s*(\d{4})", v)) and int(m.group(1)) in YEARS:
            return int(m.group(1))
    return None


def _number(items: list[str]) -> int | None:
    """ "3", "3/12" or "03" -> 3."""
    for v in items:
        if (m := re.match(r"\s*0*(\d{1,4})\s*(?:/|$)", v)) and int(m.group(1)) >= 1:
            return int(m.group(1))
    return None


def _flag(items: list[str]) -> bool:
    return any(v.strip().lower() in ("1", "true", "yes") for v in items)


def _mbid(items: list[str]) -> str | None:
    for v in items:
        if UUID.fullmatch(v := v.strip().lower()):
            return v
    return None


def _count(items: list[str]) -> int | None:
    for v in items:
        try:
            n = int(float(v))
        except ValueError:
            continue
        if n >= 0:
            return n
    return None


def to_fields(bag: Bag) -> dict:
    """The catalog fields a file's tags give (no id, no length), leaving out what isn't there."""
    bag = {k: values(v) for k, v in bag.items()}
    get = lambda k: bag.get(k) or []  # noqa: E731
    credited = get("artist")
    # Several values in the artist field itself (ID3v2.4, repeated Vorbis ARTIST): shown together, and
    # also the list, unless an ARTISTS tag gives the list.
    artist = " & ".join(credited) if credited else None
    artists = get("artists") or (credited if len(credited) > 1 else [])
    album_artist = (get("albumartist") or [None])[0]
    year, original = _year(get("date")), _year(get("originaldate"))
    fields = {
        "title": (get("title") or [None])[0],
        "artist": artist,
        "artists": artists if len(artists) > 1 else None,
        "album_artist": album_artist if album_artist and album_artist != artist else None,
        "album": (get("album") or [None])[0],
        "disc_number": _number(get("discnumber")),
        "track_number": _number(get("tracknumber")),
        "year": year,
        "original_year": original if original and original != year else None,
        "compilation": True if _flag(get("compilation")) else None,
        "genres": get("genre") or None,
        "composers": get("composer") or None,
        "label": (get("label") or [None])[0],
        "play_count": _count(get("playcount")),
        "musicbrainz_id": _mbid(get("mb_recording")),
        "musicbrainz_release_group_id": _mbid(get("mb_releasegroup")),
        "musicbrainz_artist_id": _mbid(get("mb_artist")),
    }
    fields["_release"] = _mbid(get("mb_release"))
    # Which useful tags the file has, for the tag report's coverage (an original year counts even when
    # it's the same as the year, so isn't sent).
    have = {"date": year, "originaldate": original, "albumartist": album_artist, "genre": get("genre")}
    have["mb_recording"] = fields["musicbrainz_id"]
    fields["_seen"] = sorted(k for k, v in have.items() if v)
    return {k: v for k, v in fields.items() if v is not None}


def read(path: str | Path) -> Tags:
    """One file's tags. Raises Unreadable for a file that isn't audio Booth reads; other exceptions mean a
    damaged file."""
    try:
        f = mutagen.File(path, options=FORMATS)
    except mutagen.MutagenError as e:
        raise Unreadable(str(e) or type(e).__name__) from None
    if f is None:
        raise Unreadable("not a format Booth reads")
    length = getattr(f.info, "length", 0) or 0
    out = Tags(fields={})
    tags = f.tags
    if tags is None:
        bag: Bag = {}
    elif isinstance(tags, ID3):
        bag = _id3(tags, out)
    elif isinstance(f, MP4):
        bag = _mp4(tags)
    elif isinstance(f, ASF):
        bag = _asf(tags)
    else:
        bag = _vorbis(tags)
    fields = to_fields(bag)
    out.release_id = fields.pop("_release", None)
    out.seen = set(fields.pop("_seen"))
    if length > 0:
        fields["duration_ms"] = round(length * 1000)
    out.fields = fields
    out.lossless = isinstance(f, (FLAC, WAVE, AIFF)) or (
        isinstance(f, MP4) and getattr(f.info, "codec", "") == "alac"
    )
    out.bitrate = int(getattr(f.info, "bitrate", 0) or 0)
    return out

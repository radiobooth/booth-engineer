import sys
from pathlib import Path

import radiobooth

sys.path.insert(0, str(Path(__file__).parent.parent / "packaging"))
import release_notes  # noqa: E402

LOG = """# What's new

Intro.

## 0.2.0 (2026-01-02)

- Second.

## 0.1.0

- First.
"""


def test_this_version_has_notes():
    # The release workflow refuses a version without notes: catch it here, before merge.
    text = release_notes.CHANGELOG.read_text(encoding="utf-8")
    assert release_notes.notes(text, radiobooth.__version__)


def test_notes_are_one_section():
    assert release_notes.notes(LOG, "0.2.0") == "- Second."
    assert release_notes.notes(LOG, "v0.1.0") == "- First."


def test_no_section_no_notes():
    assert release_notes.notes(LOG, "0.3.0") == ""
    assert release_notes.notes(LOG, "0.1") == ""  # not a prefix match on 0.1.0
    assert release_notes.notes("## 0.4.0\n\n## 0.3.0\n- x", "0.4.0") == ""

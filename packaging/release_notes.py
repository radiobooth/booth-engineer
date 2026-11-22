"""Print one version's notes from CHANGELOG.md, for its GitHub release.

Run by the release workflow: python packaging/release_notes.py 0.5.4 > notes.md. Fails (exit 1) when the
changelog has no section for that version, or an empty one, so a release can't go out without notes.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes(text: str, version: str) -> str:
    """The body of the `## <version>` section (a date or other words may follow the version), or ""."""
    version = version.removeprefix("v")
    heading = re.compile(rf"^## {re.escape(version)}(?:\s.*)?$")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if heading.match(line):
            body = []
            for line in lines[i + 1 :]:
                if line.startswith("## "):
                    break
                body.append(line)
            return "\n".join(body).strip()
    return ""


def main() -> None:
    version = sys.argv[1]
    body = notes(CHANGELOG.read_text(encoding="utf-8"), version)
    if not body:
        sys.exit(f"CHANGELOG.md has no notes for {version}: add a '## {version}' section first")
    print(body)


if __name__ == "__main__":
    main()

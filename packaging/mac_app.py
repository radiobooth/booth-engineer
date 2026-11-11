"""Put together Radio Booth.app from the Booth programs built for each Mac chip.

Run by the release workflow on a Mac, after the launcher is compiled:

    python packaging/mac_app.py OUT_DIR LAUNCHER BOOTH_ARM64 BOOTH_X86_64

makes OUT_DIR/Radio Booth.app. See src/radiobooth/macapp.py for how the app behaves once opened.
"""

import plistlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notices import render as notices  # noqa: E402
from version_info import version  # noqa: E402

APP = "Radio Booth.app"
BUNDLE_ID = "com.radiobooth.engineer"  # the same as radiobooth.macapp.BUNDLE_ID
MIN_MACOS = "11.0"  # Big Sur, the first macOS for Apple silicon


def info_plist(v: str) -> dict:
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "Radio Booth",
        "CFBundleExecutable": "Radio Booth",
        "CFBundleIconFile": "booth",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Radio Booth",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": v,
        "CFBundleVersion": v,
        "LSApplicationCategoryType": "public.app-category.music",
        "LSMinimumSystemVersion": MIN_MACOS,
        # No window of its own (Booth shows its page in the browser), so no Dock icon for it.
        "LSUIElement": True,
        "NSHumanReadableCopyright": "Copyright © 2026 Thomas Bohmbach, Jr. GNU GPL v3 or later.",
    }


def build(out: Path, launcher: Path, arm64: Path, x86_64: Path, v: str) -> Path:
    app = out / APP
    shutil.rmtree(app, ignore_errors=True)
    macos, resources = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir()
    for src, name in ((launcher, "Radio Booth"), (arm64, "booth-arm64"), (x86_64, "booth-x86_64")):
        shutil.copy2(src, macos / name)
        (macos / name).chmod(0o755)  # artifacts lose their permissions between jobs
    shutil.copy2(Path(__file__).parent / "booth.icns", resources / "booth.icns")
    # The GPL and the notices for what's bundled travel inside the app, so self-updates carry them too.
    shutil.copy2(Path(__file__).parent.parent / "LICENSE", resources / "LICENSE")
    (resources / "NOTICES.txt").write_text(notices(), encoding="utf-8")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info_plist(v), f)
    (app / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")
    return app


if __name__ == "__main__":
    out, launcher, arm64, x86_64 = (Path(a) for a in sys.argv[1:5])
    print(build(out, launcher, arm64, x86_64, version()))

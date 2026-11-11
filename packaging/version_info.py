"""Write the Windows file details for the packaged app (what Explorer's Properties and Task Manager show).

Run by the release workflow: python packaging/version_info.py > version_info.txt, then pass it to
PyInstaller's --version-file.
"""

import re
import sys
from pathlib import Path

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Radio Booth'),
      StringStruct('FileDescription', 'Radio Booth'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'booth'),
      StringStruct('LegalCopyright', '{copyright} GNU GPL v3 or later.'),
      StringStruct('OriginalFilename', 'RadioBooth-Windows.exe'),
      StringStruct('ProductName', 'Radio Booth'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def _package(name: str) -> str:
    """A setting from the package's __init__.py, read as text: the Mac app is put together without
    installing Booth."""
    init = Path(__file__).parent.parent / "src" / "radiobooth" / "__init__.py"
    value = re.search(rf'^{name} = "([^"]+)"$', init.read_text(encoding="utf-8"), re.M).group(1)
    return value.encode("ascii").decode("unicode_escape")


def version() -> str:
    return _package("__version__")


COPYRIGHT = _package("__copyright__")
SOURCE_URL = _package("SOURCE_URL")


def render(v: str) -> str:
    parts = [int(n) for n in re.findall(r"\d+", v)[:4]]
    nums = tuple(parts + [0] * (4 - len(parts)))
    return TEMPLATE.format(nums=nums, version=v, copyright=COPYRIGHT)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # PyInstaller reads the file as UTF-8 (the copyright sign)
    print(render(version()), end="")

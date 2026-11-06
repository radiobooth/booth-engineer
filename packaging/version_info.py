"""Write the Windows file details for the packaged app (what Explorer's Properties and Task Manager show).

Run by the release workflow: python packaging/version_info.py > version_info.txt, then pass it to
PyInstaller's --version-file.
"""

import re
from pathlib import Path

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Radio Booth'),
      StringStruct('FileDescription', 'Radio Booth'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'booth'),
      StringStruct('OriginalFilename', 'RadioBooth-Windows.exe'),
      StringStruct('ProductName', 'Radio Booth'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version() -> str:
    init = Path(__file__).parent.parent / "src" / "radiobooth" / "__init__.py"
    return re.search(r'__version__ = "([^"]+)"', init.read_text(encoding="utf-8")).group(1)


def render(v: str) -> str:
    parts = [int(n) for n in re.findall(r"\d+", v)[:4]]
    nums = tuple(parts + [0] * (4 - len(parts)))
    return TEMPLATE.format(nums=nums, version=v)


if __name__ == "__main__":
    print(render(version()), end="")

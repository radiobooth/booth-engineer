"""Start Booth Engineer when you sign in to this computer, so shows arrive without opening anything.

The packaged app is first copied to a folder of its own, so tidying Downloads never breaks it (and on macOS,
a background app may not read files in Downloads at all): on Windows a folder in AppData, on a Mac the
Applications folder (see `macapp`).
Windows: a shortcut in the Startup folder starts Booth in the background (no window), and a Start-menu
shortcut opens Booth's page. macOS: a LaunchAgent, which System Settings lists under Login Items. On both,
Booth runs as the app (`booth app --background`: no window, its page a click away). Linux: a systemd user
service running `booth run`. Each runs as you, with your settings; nothing is installed system-wide.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from radiobooth import macapp

NAME = "radiobooth"


def command() -> list[str]:
    """How to start this same Booth Engineer again: the app itself, or the installed `booth` command."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    found = shutil.which("booth")
    return [found] if found else [sys.executable, "-m", "radiobooth"]


def app_home(platform: str, home: Path) -> Path:
    """Where the packaged app keeps its own copy. (The Mac app goes to Applications instead; this is where the
    Mac download kept itself before it was an app, as a bare program.)"""
    if platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
            / "Radio Booth"
            / "RadioBooth.exe"
        )
    return home / "Library" / "Application Support" / "Radio Booth" / "Radio Booth"


def keep_app(cmd: list[str], home: Path, platform: str) -> list[str]:
    """The downloaded app copied to a folder of its own, so starting at sign-in still works after the
    Downloads folder is tidied. Only for the packaged app; an installed `booth` command stays put."""
    if not getattr(sys, "frozen", False):
        return cmd
    if platform == "darwin" and (app := macapp.bundle(cmd[0])):
        return [str(macapp.launcher(macapp.install(app, home)))]
    target = app_home(platform, home)
    if Path(cmd[0]).resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.stem + ".new" + target.suffix)
        shutil.copy2(cmd[0], staged)  # a full copy first, so a failure never leaves a broken app behind
        try:
            os.replace(staged, target)
        except OSError:
            staged.unlink(missing_ok=True)
            raise OSError(
                "Booth is running from its own folder. Close the Booth window, then try again."
            ) from None
    return [str(target)]


def _com_shortcut(link: Path, target: str, args: str, workdir: str) -> None:
    """Make a Windows shortcut (.lnk) through the shell's own IShellLink, the way installers do, called
    directly rather than by starting PowerShell: a program with no window that starts PowerShell is just what
    antivirus software looks for."""
    import ctypes
    from ctypes import POINTER, WINFUNCTYPE, byref, c_ulong, c_void_p, c_wchar_p

    ole32 = ctypes.OleDLL("ole32")  # an HRESULT failure raises OSError

    class GUID(ctypes.Structure):
        _fields_ = [
            ("a", ctypes.c_ulong),
            ("b", ctypes.c_ushort),
            ("c", ctypes.c_ushort),
            ("d", ctypes.c_ubyte * 8),
        ]

    def guid(text: str) -> GUID:
        g = GUID()
        ole32.CLSIDFromString(c_wchar_p(text), byref(g))
        return g

    def method(obj: c_void_p, index: int, *argtypes, restype=ctypes.HRESULT):
        table = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        fn = WINFUNCTYPE(restype, c_void_p, *argtypes)(table[index])
        return lambda *a: fn(obj, *a)

    try:
        ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED, for this thread
        started = True
    except OSError:  # already initialised differently on this thread: fine to use as it is
        started = False
    link_obj, file_obj = c_void_p(), c_void_p()
    try:
        ole32.CoCreateInstance(
            byref(guid("{00021401-0000-0000-C000-000000000046}")),  # ShellLink
            None,
            1,  # CLSCTX_INPROC_SERVER
            byref(guid("{000214F9-0000-0000-C000-000000000046}")),  # IShellLinkW
            byref(link_obj),
        )
        method(link_obj, 20, c_wchar_p)(target)  # SetPath
        method(link_obj, 11, c_wchar_p)(args)  # SetArguments
        method(link_obj, 9, c_wchar_p)(workdir)  # SetWorkingDirectory
        method(link_obj, 0, POINTER(GUID), POINTER(c_void_p))(  # QueryInterface
            byref(guid("{0000010B-0000-0000-C000-000000000046}")),
            byref(file_obj),  # IPersistFile
        )
        method(file_obj, 6, c_wchar_p, ctypes.c_int)(str(link), 1)  # Save
    finally:
        for obj in (file_obj, link_obj):
            if obj.value:
                method(obj, 2, restype=c_ulong)()  # Release
        if started:
            ole32.CoUninitialize()


def write_shortcut(link: Path, cmd: list[str], action: str, make=None) -> None:
    """A shortcut at `link` that runs `cmd` with `action`, for the Start menu or the Startup folder."""
    import ntpath

    args = " ".join([*(f'"{c}"' for c in cmd[1:]), *([action] if action else [])])
    link.parent.mkdir(parents=True, exist_ok=True)
    (make or _com_shortcut)(link, cmd[0], args, ntpath.dirname(cmd[0]))


APP_ARGS = ["app", "--background"]


def mac_plist(cmd: list[str], log: Path) -> str:
    args = "".join(f"\n    <string>{_xml(c)}</string>" for c in [*cmd, *APP_ARGS])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{macapp.BUNDLE_ID}</string>
  <key>AssociatedBundleIdentifiers</key>
  <array>
    <string>{macapp.BUNDLE_ID}</string>
  </array>
  <key>ProgramArguments</key>
  <array>{args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>300</integer>
  <key>StandardErrorPath</key>
  <string>{_xml(str(log))}</string>
  <key>StandardOutPath</key>
  <string>{_xml(str(log))}</string>
</dict>
</plist>
"""


def systemd_unit(cmd: list[str]) -> str:
    exe = " ".join(f'"{c}"' if " " in c else c for c in [*cmd, "run"])
    return f"""[Unit]
Description=Radio Booth (Booth Engineer)
After=network-online.target

[Service]
ExecStart={exe}
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""


def checked(run, args: list[str]) -> None:
    """Run a service command; a failure becomes an OSError, so setup falls back to running Booth itself."""
    done = run(args, capture_output=True, text=True)
    if getattr(done, "returncode", 0):
        why = (getattr(done, "stderr", "") or "").strip().splitlines()
        raise OSError(f"{' '.join(args[:2])} failed" + (f": {why[-1]}" if why else ""))


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _windows_paths(home: Path) -> tuple[Path, Path]:
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programs, programs / "Startup"


def _mac_paths(home: Path) -> tuple[Path, Path]:
    return macapp.agent_plist(home), home / "Library" / "Logs"


def installed(platform: str = sys.platform, home: Path | None = None) -> bool:
    """Whether Booth is set to start at sign-in."""
    home = home or Path.home()
    if platform == "win32":
        startup = _windows_paths(home)[1]
        return (startup / "Radio Booth.lnk").exists() or (startup / "Radio Booth.cmd").exists()
    if platform == "darwin":
        return _mac_paths(home)[0].exists()
    return (home / ".config" / "systemd" / "user" / f"{NAME}.service").exists()


def outdated(platform: str = sys.platform, home: Path | None = None) -> bool:
    """Set to start the way versions before 0.2 did (`booth run` in a window), not as the app."""
    home = home or Path.home()
    if platform == "win32":
        return (_windows_paths(home)[1] / "Radio Booth.cmd").exists()
    if platform == "darwin":
        plist = _mac_paths(home)[0]
        try:
            return plist.is_file() and "<string>app</string>" not in plist.read_text(encoding="utf-8")
        except OSError:
            return False
    return False


def start_menu(home: Path | None = None, cmd: list[str] | None = None, make=None) -> None:
    """Windows: the Start-menu entry that opens Booth's page, whether or not Booth starts at sign-in. Made
    each time the app starts, so it's there for settings carried over from an older version too, and always
    points at the app as it is now."""
    home = home or Path.home()
    programs = _windows_paths(home)[0]
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "Radio Booth setup.lnk").unlink(missing_ok=True)  # setup is on Booth's page now
    write_shortcut(programs / "Radio Booth.lnk", cmd or command(), "", make)


def install(
    platform: str = sys.platform,
    home: Path | None = None,
    run=subprocess.run,
    cmd: list[str] | None = None,
    make=None,  # how a Windows shortcut is made (tests use a stand-in)
) -> str:
    """Set Booth to start at sign-in; returns what was done, in words."""
    home = home or Path.home()
    cmd = cmd or command()
    if platform in ("win32", "darwin"):
        cmd = keep_app(cmd, home, platform)
    if platform == "win32":
        programs, startup = _windows_paths(home)
        startup.mkdir(parents=True, exist_ok=True)
        (startup / "Radio Booth.cmd").unlink(missing_ok=True)  # how versions before 0.2 started
        (programs / "Radio Booth setup.lnk").unlink(missing_ok=True)  # setup is on Booth's page now
        write_shortcut(startup / "Radio Booth.lnk", cmd, " ".join(APP_ARGS), make)
        write_shortcut(programs / "Radio Booth.lnk", cmd, "", make)
        return (
            "Booth will start by itself, in the background, each time you sign in to Windows. To see its"
            " page, open Radio Booth from the Start menu."
        )
    if platform == "darwin":
        plist, logs = _mac_paths(home)
        plist.parent.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        plist.write_text(mac_plist(cmd, logs / "radiobooth.log"), encoding="utf-8")
        if os.environ.get("XPC_SERVICE_NAME") != macapp.BUNDLE_ID:
            run(["launchctl", "unload", str(plist)], capture_output=True)  # an older copy, if any
            checked(run, ["launchctl", "load", str(plist)])
        # else this is that sign-in item, running now: unloading it would stop this very Booth. It's still
        # loaded, and the new file is what starts Booth next time.
        done = "Booth now runs in the background and starts each time you sign in to this Mac."
        if macapp.bundle(cmd[0]):
            # The bare program the Mac download kept before it was an app; nothing starts it any more.
            app_home(platform, home).unlink(missing_ok=True)
            done += " To see its page, open Radio Booth from your Applications folder."
        return done
    units = home / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)
    (units / f"{NAME}.service").write_text(systemd_unit(cmd), encoding="utf-8")
    checked(run, ["systemctl", "--user", "daemon-reload"])
    checked(run, ["systemctl", "--user", "enable", f"{NAME}.service"])
    checked(run, ["systemctl", "--user", "restart", f"{NAME}.service"])  # picks up new settings too
    return f"Booth now runs as the systemd user service {NAME!r} and starts when you sign in."


def remove(platform: str = sys.platform, home: Path | None = None, run=subprocess.run) -> str:
    """Stop starting Booth at sign-in. A Booth running now keeps running."""
    home = home or Path.home()
    if platform == "win32":
        startup = _windows_paths(home)[1]
        for name in ("Radio Booth.lnk", "Radio Booth.cmd"):
            (startup / name).unlink(missing_ok=True)
        return "Booth won't start by itself any more. Open Radio Booth from the Start menu when you want it."
    if platform == "darwin":
        plist = _mac_paths(home)[0]
        # Not `launchctl unload`: that would stop this Booth too, if launchd started it.
        plist.unlink(missing_ok=True)
        return "Booth won't start by itself any more. Open Radio Booth from Applications when you want it."
    unit = home / ".config" / "systemd" / "user" / f"{NAME}.service"
    run(["systemctl", "--user", "disable", f"{NAME}.service"], capture_output=True)
    unit.unlink(missing_ok=True)
    return "Booth won't start by itself any more."

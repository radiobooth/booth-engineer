"""Start Booth Engineer when you sign in to this computer, so shows arrive without opening anything.

The packaged app is first copied to a folder of its own, so tidying Downloads never breaks it (and on macOS,
a background app may not read files in Downloads at all): on Windows a folder in AppData, on a Mac the
Applications folder (see `macapp`).
Windows: a script in the Startup folder opens `booth run` in a minimized window (close it to stop Booth
until the next sign-in), and Start-menu shortcuts start Booth or its setup. macOS: a LaunchAgent, which
System Settings lists under Login Items. Linux: a systemd user service. Each runs as you, with your
settings; nothing is installed system-wide.
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


def windows_script(cmd: list[str], action: str = "run", minimized: bool = True) -> str:
    args = " ".join(f'"{c}"' for c in cmd)
    # The file is UTF-8; switch cmd.exe to that code page so a path like C:\\Users\\José reads correctly.
    start = f'start "Radio Booth" {"/min " if minimized else ""}{args} {action}'
    return f"@echo off\r\nchcp 65001 >nul\r\n{start}\r\n"


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


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def shortcut_script(link: Path, cmd: list[str], action: str, minimized: bool) -> str:
    """PowerShell that makes a Start-menu shortcut (.lnk). The Start menu lists shortcuts, not scripts."""
    args = " ".join(f'"{c}"' for c in cmd[1:]) + (" " if cmd[1:] else "") + action
    return "; ".join(
        [
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps(str(link)) + ")",
            "$s.TargetPath = " + _ps(cmd[0]),
            "$s.Arguments = " + _ps(args),
            "$s.WorkingDirectory = " + _ps(str(Path(cmd[0]).parent)),
            f"$s.WindowStyle = {7 if minimized else 1}",
            "$s.Save()",
        ]
    )


def mac_plist(cmd: list[str], log: Path) -> str:
    args = "".join(f"\n    <string>{_xml(c)}</string>" for c in [*cmd, "run"])
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
  <true/>
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


def install(platform: str = sys.platform, home: Path | None = None, run=subprocess.run) -> str:
    """Set Booth to start at sign-in; returns what was done, in words."""
    home = home or Path.home()
    cmd = command()
    if platform in ("win32", "darwin"):
        cmd = keep_app(cmd, home, platform)
    if platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        (programs / "Startup").mkdir(parents=True, exist_ok=True)
        # Bytes, so Windows' text mode doesn't double the \r in each line ending.
        (programs / "Startup" / "Radio Booth.cmd").write_bytes(windows_script(cmd).encode())
        # In the Start menu too: one to start Booth again, one to change its settings.
        for name, action, minimized in (("Radio Booth", "run", True), ("Radio Booth setup", "setup", False)):
            script = shortcut_script(programs / f"{name}.lnk", cmd, action, minimized)
            checked(run, ["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
        return (
            "Booth will start in a small window each time you sign in to Windows. It's in the Start menu"
            " too, as 'Radio Booth' and 'Radio Booth setup'."
        )
    if platform == "darwin":
        agents, logs = home / "Library" / "LaunchAgents", home / "Library" / "Logs"
        agents.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        plist = agents / "com.radiobooth.engineer.plist"
        plist.write_text(mac_plist(cmd, logs / "radiobooth.log"), encoding="utf-8")
        run(["launchctl", "unload", str(plist)], capture_output=True)  # an older copy, if any
        checked(run, ["launchctl", "load", str(plist)])
        done = "Booth now runs in the background and starts each time you sign in to this Mac."
        if macapp.bundle(cmd[0]):
            # The bare program the Mac download kept before it was an app; nothing starts it any more.
            app_home(platform, home).unlink(missing_ok=True)
            done += " To change its settings, open Radio Booth from your Applications folder."
        return done
    units = home / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)
    (units / f"{NAME}.service").write_text(systemd_unit(cmd), encoding="utf-8")
    checked(run, ["systemctl", "--user", "daemon-reload"])
    checked(run, ["systemctl", "--user", "enable", f"{NAME}.service"])
    checked(run, ["systemctl", "--user", "restart", f"{NAME}.service"])  # picks up new settings too
    return f"Booth now runs as the systemd user service {NAME!r} and starts when you sign in."

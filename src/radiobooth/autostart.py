"""Start Booth Engineer when you sign in to this computer, so shows arrive without opening anything.

Windows: the app is copied to %LOCALAPPDATA%\\Radio Booth, and small scripts in the Startup folder and
the Start menu open `booth run` in a minimized window (close it to stop Booth until the next sign-in).
macOS: a LaunchAgent. Linux: a systemd user service. Each runs as you, with your settings; nothing is
installed system-wide.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "radiobooth"


def command() -> list[str]:
    """How to start this same Booth Engineer again: the app itself, or the installed `booth` command."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    found = shutil.which("booth")
    return [found] if found else [sys.executable, "-m", "radiobooth"]


def windows_script(cmd: list[str], action: str = "run", minimized: bool = True) -> str:
    args = " ".join(f'"{c}"' for c in cmd)
    return f'@echo off\r\nstart "Radio Booth" {"/min " if minimized else ""}{args} {action}\r\n'


def keep_app_windows(cmd: list[str], home: Path) -> list[str]:
    """The downloaded app copied to a folder of its own, so starting at sign-in still works after the
    Downloads folder is tidied. Only for the packaged app; an installed `booth` command stays put."""
    if not getattr(sys, "frozen", False):
        return cmd
    folder = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Radio Booth"
    target = folder / "RadioBooth.exe"
    if Path(cmd[0]).resolve() != target.resolve():
        folder.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(cmd[0], target)
        except OSError:  # most likely that copy is running right now: it's already there
            if not target.exists():
                raise
    return [str(target)]


def mac_plist(cmd: list[str], log: Path) -> str:
    args = "".join(f"\n    <string>{_xml(c)}</string>" for c in [*cmd, "run"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.radiobooth.engineer</string>
  <key>ProgramArguments</key>
  <array>{args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
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


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def install(platform: str = sys.platform, home: Path | None = None, run=subprocess.run) -> str:
    """Set Booth to start at sign-in; returns what was done, in words."""
    home = home or Path.home()
    cmd = command()
    if platform == "win32":
        cmd = keep_app_windows(cmd, home)
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        (programs / "Startup").mkdir(parents=True, exist_ok=True)
        (programs / "Startup" / "Radio Booth.cmd").write_text(windows_script(cmd), encoding="utf-8")
        # In the Start menu too: one to start Booth again, one to change its settings.
        (programs / "Radio Booth.cmd").write_text(windows_script(cmd), encoding="utf-8")
        (programs / "Radio Booth setup.cmd").write_text(
            windows_script(cmd, "setup", minimized=False), "utf-8"
        )
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
        run(["launchctl", "unload", str(plist)], capture_output=True)
        run(["launchctl", "load", str(plist)], capture_output=True)
        return "Booth now runs in the background and starts each time you sign in to this Mac."
    units = home / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)
    (units / f"{NAME}.service").write_text(systemd_unit(cmd), encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    run(["systemctl", "--user", "enable", "--now", f"{NAME}.service"], capture_output=True)
    return f"Booth now runs as the systemd user service {NAME!r} and starts when you sign in."

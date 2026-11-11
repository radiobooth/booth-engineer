# Packaging

Files the release workflow uses to build the double-click apps.

- `booth.ico`: the Windows app icon, from the Radio Booth brand kit (On Air). 32 px and up are the app icon
  with rounded corners; 16 to 24 px are just the lit on-air light, as the kit says for small sizes.
- `version_info.py`: writes the Windows file details (name "Radio Booth", version from `radiobooth`), and
  holds the copyright line the apps use.
- `notices.py`: writes `NOTICES.txt` (the copyright, the GPL, where the source is, and the licenses of the
  Python and PyInstaller bootloader bundled in the apps). It goes inside each program with `LICENSE`, in the
  Mac app's Resources, and next to the downloads.
- `booth.icns`: the Mac app icon, from the same kit: the 1024 icon drawn on Apple's icon grid (an 824 px
  rounded square with a soft shadow), and the lit light alone at 16 px.
- `macos/launcher.c`: the Mac app's main program. Built for both chips in one file; it starts the Booth
  program for the Mac it's on (`booth-arm64` or `booth-x86_64`, from two release runners).
- `mac_app.py`: puts `Radio Booth.app` together from those (Info.plist, icon, programs). The workflow then
  signs it ad hoc and zips it with `ditto`. How the app behaves once opened is in `src/radiobooth/macapp.py`.

The Mac app isn't signed with an Apple Developer ID or notarized yet, so macOS asks once before opening it
(System Settings > Privacy & Security > Open Anyway). Signing and notarizing needs a paid Apple Developer
account; with one, the workflow would sign with that certificate and run `notarytool` instead of signing ad
hoc, and the question goes away.

## How the apps run

Neither app has a window of its own. Opened, Booth starts in the background and opens its page in the
browser (`src/radiobooth/web.py`, served on 127.0.0.1 only); opened again, it just opens that page. The
Windows build is made with `--noconsole`, so its messages go to `booth.log` next to the config file. Both
apps update themselves from GitHub releases (`src/radiobooth/update.py`): the release workflow publishes
`SHA256SUMS` with the downloads, and an app installs only a download that matches it.

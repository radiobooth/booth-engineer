<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="images/logo-horizontal-on-light.svg" width="280">
</picture>

# Other ways to set up Booth

[Getting started](getting-started.md) covers the usual setups: Booth runs on a Windows PC or Mac, either the
one with your music or another one on your home network that reaches it (a NAS, a media PC). This page covers
the rest:

- [Linux](#linux)
- [Docker, for example on a NAS](#docker-for-example-on-a-nas)
- [Booth as a command on a Mac](#booth-as-a-command-on-a-mac)
- [What isn't supported yet](#what-isnt-supported-yet)

<a id="plex-runs-on-a-different-computer"></a><a id="what-you-set-up-on-the-plex-side-once"></a>

Plex or your music on a different computer from Booth? That's in Getting started now:
[Music on another computer](getting-started.md#music-on-another-computer).

## Linux

There's no double-click app for Linux yet; Booth installs as a command. You need
[uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv tool install git+https://github.com/radiobooth/booth-engineer@v0.1.2
booth setup
```

`booth setup` is the same guided setup as the apps: it prints a Plex sign-in link to open in any browser,
asks a few questions, and pairs with your Booth account. To update Booth later, run the
`uv tool install` line again with the newer version and `--force`.

If you say yes to starting automatically, Booth installs a systemd user service called `radiobooth`.
Check it with `systemctl --user status radiobooth` and read its log with `journalctl --user -u radiobooth`.
A user service only runs while you're signed in. On a headless machine, let it run without a sign-in:

```sh
sudo loginctl enable-linger "$USER"
```

**Plex on the same Linux machine.** Setup makes the `Radio Booth` library in Plex for you. Plex installed
from its Linux package runs as its own `plex` user, which often can't look inside your home folder, so setup
checks that Plex can read the folder it picks: `~/Radio Booth` if it can, otherwise a `Radio Booth` folder
next to one of your Plex library folders (for example `/srv/Radio Booth` next to `/srv/music`). If neither
works (you can't write next to your music), setup says so; then make the library yourself, in a folder Plex
can read and you can write to, as in [the Plex side](getting-started.md#with-plex), and run
setup again.

**Plex on another machine.** Mount the shared folder first, permanently (an `/etc/fstab` entry for SMB or
NFS, not a desktop file-manager mount, which goes away when you sign out). Then follow
[Music on another computer](getting-started.md#with-plex) and give setup the mounted path.

## Docker, for example on a NAS

Running Booth in a container on the NAS that runs Plex keeps it on all the time, with no other computer
involved. There isn't a published image yet, so build it from this repository (a NAS that can build images
from a Git address can do the same):

```sh
docker build -t booth-engineer https://github.com/radiobooth/booth-engineer.git#v0.1.2
```

1. **Make the `Radio Booth` library in Plex first**, as in
   [the Plex side](getting-started.md#with-plex). Note the folder path Plex shows, for
   example `/volume1/audio/Radio Booth`. (If Plex itself runs in a container, use the path on the NAS, not
   the one inside Plex's container.)
2. **Run setup once**, giving the container that folder as `/breaks`:

   ```sh
   docker run -it --rm \
     -v booth-config:/config \
     -v "/volume1/audio/Radio Booth:/breaks" \
     booth-engineer setup
   ```

   Open the Plex sign-in link it prints in a browser on any device. When it asks where the folder is from
   this computer, type `/breaks`. Say **no** to starting automatically; Docker does that instead. Setup ends
   by running Booth in the window: press Ctrl+C to stop it.
3. **Start it for good:**

   ```sh
   docker run -d --name booth --restart unless-stopped \
     -v booth-config:/config \
     -v "/volume1/audio/Radio Booth:/breaks" \
     booth-engineer
   ```

Docker's normal network and host networking both work. Either way, Booth in a container treats Plex as
being on another computer, since the two don't see the same folders, which is why it asks for `/breaks`.

Settings and the pairing live in the `booth-config` volume. You can also set everything by environment
instead of running setup (`PLEX_URL`, `PLEX_TOKEN`, `BOOTH_BREAKS_LIBRARY`, `BOOTH_BREAKS_DIR`, see the
[README](../README.md#by-hand)), but you still need `booth pair` once, with `-it`, for the pairing code.

<a id="an-intel-mac"></a>

## Booth as a command on a Mac

The Radio Booth app works on Apple silicon and Intel Macs alike (from version 0.1.3). If you'd rather have
Booth as a command, for example on a Mac you reach over SSH, install it with
[uv](https://docs.astral.sh/uv/getting-started/installation/), in Terminal:

```sh
uv tool install git+https://github.com/radiobooth/booth-engineer@v0.2.0
booth setup
```

Setup is the same as the app's, and saying yes to starting automatically works the same way.

## What isn't supported yet

- **Plex servers we can't write a folder for.** Booth delivers breaks as files Plex scans, so it needs a
  folder that Plex watches and that Booth can write to. Shared Plex servers you don't own won't work, and
  neither will hosted Plex services that don't give you a folder.
- **A shared folder over the internet.** Booth and the Plex computer need to be on the same home network,
  unless Booth runs on the Plex computer itself.
- **Making the `Radio Booth` library from another computer.** Setup only makes it automatically when Plex
  runs on the same computer. Otherwise you make it in Plex, as above.
- **Music servers other than Plex.** Not yet.
- **A download for Linux, and a published Docker image.** For now these install from this
  repository, as above.

Stuck? Get in touch with the person who invited you, and say which of these setups you're trying.

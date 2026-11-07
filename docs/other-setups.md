<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="images/logo-horizontal-on-light.svg" width="280">
</picture>

# Other ways to set up Booth

[Getting started](getting-started.md) covers the usual setup: Booth runs on the same Windows PC or Mac as
Plex. This page covers the rest:

- [Plex runs on a different computer](#plex-runs-on-a-different-computer) (a NAS, a media PC, a server)
- [Linux](#linux)
- [Docker, for example on a NAS](#docker-for-example-on-a-nas)
- [Booth as a command on a Mac](#booth-as-a-command-on-a-mac)
- [What isn't supported yet](#what-isnt-supported-yet)

## First, the choice: where should Booth run?

Booth does two things on your side: it reads your music library from Plex, and it puts the DJ's voice clips
(the breaks) in a folder that Plex watches. So it needs to reach Plex over your home network **and** write
to one of Plex's folders.

When Booth runs on the Plex computer, both are automatic. When it runs somewhere else, you set up a shared
folder by hand. So, best first:

1. **On the Plex computer.** If that's a Windows PC or a Mac, use
   [Getting started](getting-started.md). If it's a Linux machine, see [Linux](#linux). If it's a NAS that
   runs Docker containers (Synology, QNAP, Unraid and others), see [Docker](#docker-for-example-on-a-nas).
2. **On another computer in the same home**, with a shared folder. See the next section.

Either way, the computer running Booth has to be on and awake when you ask for a show.

## Plex runs on a different computer

For example, Plex is on a NAS and Booth runs on your laptop or desktop. This works as long as both are on
the same home network, and the computer running Booth can open a shared folder on the Plex computer.

### What you set up on the Plex side (once)

1. **Make a folder for the breaks** on the Plex computer, or on a drive it uses. Call it `Radio Booth`.
   Keep it outside your music folders, so the DJ never shows up among your own songs. For example, on a
   Synology NAS: a `Radio Booth` folder inside your shared folder for audio.
2. **Add it to Plex as a music library named exactly `Radio Booth`.** In Plex, click **+** next to your
   libraries (or **Settings > Manage > Libraries > Add Library**), choose **Music**, name it
   `Radio Booth`, and add the folder from step 1. Plex shows the folder's path as it sees it, for example
   `/volume1/audio/Radio Booth`. Booth will mention that path later.
3. **Share the folder so your other computer can write to it.** On a NAS, the folder is usually already in
   a shared folder; make sure the account you use from your computer can write there. Plex itself only
   needs to read it. (On a Synology NAS, the Plex package needs read permission on that shared folder:
   **Control Panel > Shared Folder > Edit > Permissions**, then the user `PlexMediaServer`.)

### What you set up on the computer running Booth

1. **Connect to the shared folder** and check you can open the `Radio Booth` folder, then copy its path:
   - **Windows:** in File Explorer, go to **Network**, then your NAS or Plex computer, then the folder.
     Hold **Shift**, right-click the `Radio Booth` folder and choose **Copy as path**. It looks like
     `"\\MyNAS\audio\Radio Booth"`. Use this kind of address rather than a drive letter like `Z:`, which
     may not be connected yet when Booth starts.
   - **Mac:** in Finder, choose **Go > Connect to Server**, type `smb://` and your NAS or Plex computer's
     name (for example `smb://mynas.local`), and pick the shared folder. Then find the `Radio Booth` folder,
     hold **Option**, right-click it and choose **Copy "Radio Booth" as Pathname**. It looks like
     `/Volumes/audio/Radio Booth`.
2. **Download and open Booth**, as in steps 2 and 3 of [Getting started](getting-started.md).
3. **Sign in to Plex** and pick your server and music library, as usual. Booth notices that Plex runs on
   another computer and says so. It shows where your `Radio Booth` library is on the Plex computer, and asks:
   **"Where is that same folder from this computer?"** Paste the path you copied and press Enter.
4. **Finish the other steps** as in [Getting started](getting-started.md).

If Booth instead lists steps to make a folder and a library, the `Radio Booth` library isn't in Plex yet (or
has a different name). Do the Plex side above, then open Booth again.

### Keep the shared folder connected

Booth puts every show's breaks in that folder, so it must be connected whenever Booth delivers a show. If it
isn't, the show says **Didn't work** on your phone; reconnect the folder and ask again.

- **Windows:** the `\\MyNAS\...` address reconnects by itself once your computer is signed in and on the
  network. If your NAS asks for a password, tick **Remember my credentials** the first time.
- **Mac:** shared folders don't reconnect by themselves after a restart. To make them, open
  **System Settings > General > Login Items**, click **+** under "Open at Login", and choose the shared
  folder (it's under **Locations** in the Finder sidebar while connected). If your Mac asks whether Radio
  Booth may access files on a network volume, click **Allow**.

### Good to know

- Booth reaches Plex the way the Plex apps do, using the addresses your Plex server publishes, closest
  first. Nothing to type.
- Booth only connects out. It never opens anything on your computer or your Plex server to the internet.
- Both computers need to be at home, on the same network. Booth can reach Plex from elsewhere through Plex's
  remote access, but a shared folder from across the internet isn't something we support.

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
can read and you can write to, as in [the Plex side](#what-you-set-up-on-the-plex-side-once) above, and run
setup again.

**Plex on another machine.** Mount the shared folder first, permanently (an `/etc/fstab` entry for SMB or
NFS, not a desktop file-manager mount, which goes away when you sign out). Then follow
[Plex runs on a different computer](#plex-runs-on-a-different-computer) and give setup the mounted path.

## Docker, for example on a NAS

Running Booth in a container on the NAS that runs Plex keeps it on all the time, with no other computer
involved. There isn't a published image yet, so build it from this repository (a NAS that can build images
from a Git address can do the same):

```sh
docker build -t booth-engineer https://github.com/radiobooth/booth-engineer.git#v0.1.2
```

1. **Make the `Radio Booth` library in Plex first**, as in
   [the Plex side](#what-you-set-up-on-the-plex-side-once) above. Note the folder path Plex shows, for
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
uv tool install git+https://github.com/radiobooth/booth-engineer@v0.1.3
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

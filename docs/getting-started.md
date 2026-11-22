<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="images/logo-horizontal-on-light.svg" width="280">
</picture>

# Getting started with Radio Booth

Radio Booth makes radio shows from your own music, with a DJ talking between songs. You ask for a show on
your phone ("Sunday morning coffee, an hour"), and a few minutes later it's a playlist in Plex.

This takes about 10 minutes, once.

## What you need

- **Your music**, either in **Plex Media Server** or simply as a folder of music files (MP3, FLAC, M4A and
  the like). It can be on any computer in your home: a NAS, a media PC, an old computer in a closet, or the
  one in front of you.
- **A Windows PC or a Mac to run Booth.** Either the computer your music is on, or any other one at home that
  can reach it over your home network. It needs to be on and awake when you ask for a show, and doesn't need
  to stay on otherwise.
- **Your phone**, with the sign-in link you were sent.

### Where should Booth run?

- **On the computer with your music** (it runs Plex, or your music folder is on its own drive): everything
  is found for you. Follow the steps below as they are.
- **On another computer on your home network**, when your music lives on a NAS or another machine: this
  works just as well. You connect that computer to the shared folder once, and paste its path into Booth.
  Read [Music on another computer](#music-on-another-computer) first, then follow the steps below.

If your NAS can run apps itself (Docker), or the music computer runs Linux, Booth can run there too: see
[Other ways to set up Booth](other-setups.md).

## 1. Sign in on your phone

Open the sign-in link you were sent, on your phone. You'll see your Booth page. Keep it handy: add it to
your home screen or bookmark it. The link is yours alone; please don't share it.

## 2. Download Booth on the computer with your music

Go to the [latest release](https://github.com/radiobooth/booth-engineer/releases/latest) and download:

- **Windows:** `RadioBooth-Windows.exe`. Your browser may warn that the file "isn't commonly downloaded",
  because Booth is new. It's safe to keep: in **Chrome**, click **Keep** (or **Download suspicious file**);
  in **Edge**, click the **...** next to the download, then **Keep**, **Show more** and **Keep anyway**.
- **Mac:** `RadioBooth-macOS.zip`. Safari unzips it for you; with another browser, double-click it in
  Downloads. You get the **Radio Booth** app. It works on any Mac from macOS 11 (Big Sur) on, Apple silicon
  or Intel.

## 3. Open it

**Windows:** double-click `RadioBooth-Windows.exe`. Windows may show a blue box saying "Windows protected
your PC", because Booth is new and not yet known to Microsoft. Click **More info**, then **Run anyway**.

**Mac:** double-click **Radio Booth** in Downloads. The first time, your Mac says it can't check Radio
Booth for malicious software, because Booth is new and not yet registered with Apple. Click **Done**, then
open **System Settings > Privacy & Security**, scroll down, click **Open Anyway** next to "Radio Booth" and
confirm with your password. (On macOS 11 or 12 it's **System Preferences > Security & Privacy**.) Booth then
moves itself into your Applications folder, so you can delete the download, and opens.

Your browser opens **Booth's page** (this one is on the computer; the Booth page on your phone is the other
one). That's Booth. There's no other window: Booth runs in the background.

## 4. Follow the two steps on Booth's page

**Your music in Plex.** Click **It's in Plex**. Plex's own sign-in page opens in a new tab: sign in and allow
Radio Booth. (Booth never sees your Plex password.) Then come back to Booth's tab. If you have more than one
Plex server or music library, click the one with your music.

Booth then adds a small library to Plex called **Radio Booth**. The DJ's voice clips go there, so they never
mix into your own music. If Plex runs on another computer, Booth asks where that library's folder is from this
computer instead: see [Music on another computer](#music-on-another-computer).

**Your music in a folder.** Click **It's in a folder**. Type (or paste) the folder your music is in, and the
folder for your shows; Booth suggests both. To copy a folder's path, click the address bar in File Explorer,
or in Finder select the folder, hold **Option** and choose **Copy as Pathname**. A shared folder on a NAS or
another computer works too ([how](#with-a-folder)). Click **Use these folders**,
and Booth starts reading your music's tags, with a progress bar. A big collection takes a while the first time
(tens of minutes for tens of thousands of songs); after that Booth only reads what's new. You can do the next
step meanwhile. Each show arrives in your shows folder as a playlist: open it in your music player
(foobar2000, MusicBee, VLC, Music on a Mac, and most others). Booth never changes or moves your music files.

**Your Booth account.** On your phone's Booth page, tap **Get a pairing code**. Type the code into Booth's
page on the computer and click **Connect**. The code works once and lasts 10 minutes.

When both are done, the light at the top of Booth's page turns red and says **On air**. Booth also sets
itself to start by itself, in the background, whenever you sign in to the computer. (You can turn that off
on Booth's page under **Settings**.)

You can close the browser tab: Booth keeps running. To see Booth's page again, open **Radio Booth** from the
Start menu (Windows) or from Applications, Launchpad or Spotlight (Mac). On a Mac you may see a note that a
background item was added; that's Booth, and it's listed under **System Settings > General > Login Items**.

That's it.

## 5. Ask for a show

On your phone, or on Booth's page on the computer, describe the show, pick a length and a DJ, and tap **Make
the show**. The page tells you how it's going. When it says **In Plex**, open Plex and look under
**Playlists**. With your music in a folder, it says **In your Booth shows folder**: open the new playlist
there in your music player. **Remove** under a show on Booth's page deletes its playlist and DJ breaks
(in Plex, or in your Booth shows folder). To take a show with you, click **Copy to a folder** under it: Booth copies its songs and breaks into a folder
of their own, numbered in order, and opens that folder. Drag it onto your phone, a USB stick or your car's
drive, and it plays in order even in a player that ignores playlists. Or click **Make one file**: Booth mixes
the show into a single MP3, crossfaded like the radio, with a chapter for each song and break. Some players, VLC among them, don't show MP3
chapters: open the `.cue` file next to the MP3 instead and they list every song and break. A 2-hour show
takes a few minutes to make. With Plex, both go into `Copies` in the `Booth shows` folder in your home
folder (or in `BOOTH_SHOWS_FOLDER`, when that's set), and Booth fetches the songs from your Plex server first.

If your account has a limit, both pages show what's left above the form.

## 6. Tell us what you think

Once a show is in Plex, your phone's Booth page shows **How was it?** under it. Tap it to give the show 1 to 5
stars and, if you like, a note. Below that are the show's breaks (the bits where the DJ talks), numbered the
same as in Plex. If the DJ got something wrong, said a name wrong, sounded off, or went on too long, tap
**Flag this break** and pick what happened. That's the most useful thing you can do for us: every rating and
flag is read.

For anything bigger, questions, or ideas, come say hi in the [Radio Booth Discord](https://discord.gg/aN2bNKB74y), where testers and
the people making Booth talk.

## Music on another computer

Your music is on a NAS, a media PC or another computer, and Booth runs on a Windows PC or Mac in the same home.
Booth reaches your music over your home network; nothing is opened to the internet.

### With Plex

Booth reads your library from Plex over the network by itself. The one thing it needs is a folder for the DJ's
breaks that **Plex watches and this computer can write to**, so you set that up once.

**On the Plex side:**

1. **Make a folder for the breaks** on the Plex computer, or on a drive it uses. Call it `Radio Booth`.
   Keep it outside your music folders, so the DJ never shows up among your own songs. For example, on a
   Synology NAS: a `Radio Booth` folder inside your shared folder for audio.
2. **Add it to Plex as a music library named exactly `Radio Booth`.** In Plex, click **+** next to your
   libraries (or **Settings > Manage > Libraries > Add Library**), choose **Music**, name it
   `Radio Booth`, and add the folder from step 1.
3. **Make sure your computer can write to it.** On a NAS, the folder is usually already in a shared folder;
   check that the account you use from your computer can write there. Plex itself only needs to read it. (On
   a Synology NAS, the Plex package needs read permission on that shared folder: **Control Panel > Shared
   Folder > Edit > Permissions**, then the user `PlexMediaServer`.)

**On the computer running Booth:**

1. **Connect to the shared folder and copy its path** (see [Copying a shared folder's path](#copying-a-shared-folders-path)).
2. **Download and open Booth** and click **It's in Plex**, as in steps 2 to 4 above. Booth notices that Plex
   runs on another computer, shows where the `Radio Booth` folder is there, and asks **where that same folder
   is from this computer**. Paste the path you copied.

If Booth instead says to make a folder and a library, the `Radio Booth` library isn't in Plex yet (or has a
different name). Do the Plex side above, then try again.

### With a folder

1. **Connect to the shared folder your music is in, and copy its path** (see below).
2. **Click It's in a folder** on Booth's page and paste it as your music folder.
3. **For the shows folder**, either keep the one Booth suggests on this computer, or put it on the NAS too
   (for example a `Booth shows` folder next to your music), so other computers and players at home can open
   the shows. Booth writes playlists that work from any computer that sees the same folder.

The first read of a big collection over the network takes longer than from a local drive; Booth shows a
progress bar, and after that it only reads what's new.

### Copying a shared folder's path

- **Windows:** in File Explorer, go to **Network**, then your NAS or other computer, then the folder. Hold
  **Shift**, right-click the folder and choose **Copy as path**. It looks like `"\\MyNAS\audio\Radio Booth"`.
  Use this kind of address rather than a drive letter like `Z:`, which may not be connected yet when Booth
  starts.
- **Mac:** in Finder, choose **Go > Connect to Server**, type `smb://` and the NAS or computer's name (for
  example `smb://mynas.local`), and pick the shared folder. Then find the folder, hold **Option**, right-click
  it and choose **Copy "…" as Pathname**. It looks like `/Volumes/audio/Radio Booth`.

### Keep the shared folder connected

Booth uses that folder for every show, so it must be connected whenever Booth makes one. If it isn't, the show
says **Didn't work** on your phone; reconnect the folder and ask again.

- **Windows:** a `\\MyNAS\...` address reconnects by itself once your computer is signed in and on the
  network. If your NAS asks for a password, tick **Remember my credentials** the first time.
- **Mac:** shared folders don't reconnect by themselves after a restart. To make them, open
  **System Settings > General > Login Items**, click **+** under "Open at Login", and choose the shared
  folder (it's under **Locations** in the Finder sidebar while connected). If your Mac asks whether Radio
  Booth may access files on a network volume, click **Allow**.

Both computers need to be at home, on the same network. A shared folder across the internet isn't supported.

## Sharing Booth with someone in your home

Someone else with their own Radio Booth account can use your Booth too, so they don't need Booth on a computer
of their own. On Booth's page, under **Settings**, click **Add another person**. On their phone, signed in to
their own account, they tap **Get a pairing code**; type that code into Booth's page and click **Add**.

Their shows are made from the same music and go into the same Plex, with their name at the start of each
playlist (for example "Jennifer: Rainy drive home"). They count against their own show time, and Booth keeps
a separate history for them, so their shows don't skip tracks just because they were in yours. On Booth's
page, **Who's it for** on the New show form picks whose show it is.

To have their shows show up in their own Plex, pick their Plex user under **Share their playlists in Plex
with** next to their name. Booth then shares each new playlist of theirs with them, and they find it in Plexamp
under **Shared Playlists**. They need to be able to see the **Radio Booth** library in Plex too, or the DJ's
breaks won't play for them; Booth tells you if they can't. To stop, click **Remove** next to their
name. If they also run Booth on a computer of their own, shows they ask for on their phone may go to either
one, so it's simplest to keep just one.

## Listening away from home

If it's switched on for you (testers, for now), each show that reached your computer has **Get the file** on
the phone page. Booth, on the computer at home, mixes the show into one MP3 and sends it to your phone, which
takes a minute or two (the computer has to be on). Then tap **Download**. On an iPhone the file goes to
**Files › Downloads**; on Android, to **Downloads**. Radio Booth deletes its copy an hour after you download
it, or after a day if you don't.

## What Booth sends, and what it doesn't

When you ask for a show, and only then, Booth sends the details of your music library: titles, artists,
albums, years, genres, ratings, play counts, when you added things, and which songs were in your recent
shows. That's what the DJ uses to pick songs and talk about them. Radio Booth uses it to make that one show
and doesn't keep it afterwards. While the show is made, the AI services that write and voice it (Claude, by
Anthropic, and Google Cloud's text-to-speech) process the parts they need, under business terms that don't
let them train on it.

Radio Booth does keep a short record of each show: what you asked for, its title, whether it reached Plex,
and what it cost to make.

Your music files never leave your computer, unless you ask to download a show on your phone: then that one
show, mixed into one MP3, goes up to Radio Booth for your phone to fetch, and Radio Booth deletes it an hour
after you download it (or after a day, if you don't). Booth only ever connects out: to Plex, to Radio Booth, and to
GitHub to check for updates. Nothing on the internet, or on your home network, can connect in to your
computer through it. Booth's page is shown only on the computer Booth runs on.

The full details are in [`protocol/`](../protocol/).

## If something goes wrong

Open **Radio Booth** (Start menu, or Applications on a Mac) to see Booth's page. The box at the top says what
Booth is doing and, if something needs you, what to do.

- **The show stays at "Waiting for your Booth Engineer".** Booth isn't running, or the computer is asleep.
  Open **Radio Booth**; that starts it. Booth's page should then say **On air**.
- **"Didn't work".** The reason is shown under the show. Try again; if it keeps happening, tell us in the
  [Discord](https://discord.gg/aN2bNKB74y) what it says, and what Booth's page shows under **What Booth has been doing**.
- **You changed your Plex setup, or moved your music.** On Booth's page, click **Change** next to
  **Change Booth's setup**, then **Sign in to Plex again** (or **Change folders**).
- **Booth's page says "Booth isn't running".** Open **Radio Booth** again.

## Updating Booth

You don't need to: Booth updates itself. Every few hours it checks for a new version, and installs it when
no show is on its way to Plex. Booth's page shows which version you have, under **Settings**.

Anything else: ask in the [Radio Booth Discord](https://discord.gg/aN2bNKB74y), or get in touch with the person
who invited you.

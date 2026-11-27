<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="images/logo-horizontal-on-light.svg" width="280">
</picture>

# Getting started with Radio Booth

Radio Booth makes radio shows from your own music, with a DJ talking between songs. You ask for a show on
your phone ("Sunday morning coffee, an hour"), and a few minutes later it's a playlist in Plex. If you use
Claude, ChatGPT or Gemini, you can also ask it for shows in a chat: see
[Make shows with your own AI assistant](#make-shows-with-your-own-ai-assistant).

This takes about 10 minutes, once.

## What you need

- **Your music**, either in **Plex Media Server** or simply as a folder of music files (MP3, FLAC, M4A and
  the like). It can be on any computer in your home: a NAS, a media PC, an old computer in a closet, or the
  one in front of you.
- **A Windows PC or a Mac to run Radio Booth.** Either the computer your music is on, or any other one at home that
  can reach it over your home network. It needs to be on and awake when you ask for a show, and doesn't need
  to stay on otherwise.
- **Your phone**, with the sign-in link you were sent.

### Where should Radio Booth run?

- **On the computer with your music** (it runs Plex, or your music folder is on its own drive): everything
  is found for you. Follow the steps below as they are.
- **On another computer on your home network**, when your music lives on a NAS or another machine: this
  works just as well. You connect that computer to the shared folder once, and paste its path into Radio Booth.
  Read [Music on another computer](#music-on-another-computer) first, then follow the steps below.

If your NAS can run apps itself (Docker), or the music computer runs Linux, Radio Booth can run there too: see
[Other ways to set up Radio Booth](other-setups.md).

## 1. Sign in on your phone

Open the sign-in link you were sent, on your phone. You'll see your Radio Booth page. Keep it handy: add it to
your home screen or bookmark it. The link is yours alone; please don't share it.

## 2. Download Radio Booth on the computer with your music

Go to the [latest release](https://github.com/radiobooth/engineer/releases/latest) and download:

- **Windows:** `RadioBooth-Windows.exe`. Your browser may warn that the file "isn't commonly downloaded",
  because Radio Booth is new. It's safe to keep: in **Chrome**, click **Keep** (or **Download suspicious file**);
  in **Edge**, click the **...** next to the download, then **Keep**, **Show more** and **Keep anyway**.
- **Mac:** `RadioBooth-macOS.zip`. Safari unzips it for you; with another browser, double-click it in
  Downloads. You get the **Radio Booth** app. It works on any Mac from macOS 11 (Big Sur) on, Apple silicon
  or Intel.

## 3. Open it

**Windows:** double-click `RadioBooth-Windows.exe`. Windows may show a blue box saying "Windows protected
your PC", because Radio Booth is new and not yet known to Microsoft. Click **More info**, then **Run anyway**.

**Mac:** double-click **Radio Booth** in Downloads. The first time, your Mac says it can't check Radio
Radio Booth for malicious software, because Radio Booth is new and not yet registered with Apple. Click **Done**, then
open **System Settings > Privacy & Security**, scroll down, click **Open Anyway** next to "Radio Booth" and
confirm with your password. (On macOS 11 or 12 it's **System Preferences > Security & Privacy**.) Radio Booth then
moves itself into your Applications folder, so you can delete the download, and opens.

Your browser opens **Radio Booth's page** (this one is on the computer; the Radio Booth page on your phone is the other
one). That's Radio Booth. There's no other window: Radio Booth runs in the background.

## 4. Follow the two steps on Radio Booth's page

**Your music in Plex.** Click **It's in Plex**. Plex's own sign-in page opens in a new tab: sign in and allow
Radio Booth. (Radio Booth never sees your Plex password.) Then come back to Radio Booth's tab. If you have more than one
Plex server or music library, click the one with your music.

Radio Booth then adds a small library to Plex called **Radio Booth**. The DJ's voice clips go there, so they never
mix into your own music. If Plex runs on another computer, Radio Booth asks where that library's folder is from this
computer instead: see [Music on another computer](#music-on-another-computer).

**Your music in a folder.** Click **It's in a folder**. Type (or paste) the folder your music is in, and the
folder for your shows; Radio Booth suggests both. To copy a folder's path, click the address bar in File Explorer,
or in Finder select the folder, hold **Option** and choose **Copy as Pathname**. A shared folder on a NAS or
another computer works too ([how](#with-a-folder)). Click **Use these folders**,
and Radio Booth starts reading your music's tags, with a progress bar. A big collection takes a while the first time
(tens of minutes for tens of thousands of songs); after that Radio Booth only reads what's new. You can do the next
step meanwhile. Each show arrives in your shows folder as a playlist: open it in your music player
(foobar2000, MusicBee, VLC, Music on a Mac, and most others). Radio Booth never changes or moves your music files.

**Your Radio Booth account.** On your phone's Radio Booth page, tap **Get a pairing code**. Type the code into Radio Booth's
page on the computer and click **Connect**. The code works once and lasts 10 minutes.

When both are done, the light at the top of Radio Booth's page turns red and says **On air**. Radio Booth also sets
itself to start by itself, in the background, whenever you sign in to the computer. (You can turn that off
on Radio Booth's page under **Settings**.)

You can close the browser tab: Radio Booth keeps running. To see Radio Booth's page again, open **Radio Booth** from the
Start menu (Windows) or from Applications, Launchpad or Spotlight (Mac). On a Mac you may see a note that a
background item was added; that's Radio Booth, and it's listed under **System Settings > General > Login Items**.

That's it.

## 5. Ask for a show

On your phone's Radio Booth page, describe the show, pick a length and a DJ, and tap **Make the show**. (Radio Booth's page
on the computer shows that page's QR code under **Make a show on your phone**: scan it with your phone's camera
to open it. **Open it here** opens it on the computer instead.) The phone page tells you how it's going. When it says **In Plex**, open Plex and look under
**Playlists**. With your music in a folder, it says **In your shows folder**: open the new playlist
there in your music player. Radio Booth's page on the computer lists your latest shows too, under **Your shows**. **Remove** under a show there deletes its playlist and DJ breaks
(in Plex, or in your shows folder). To take a show with you, click **Copy to a folder** under it: Radio Booth copies its songs and breaks into a folder
of their own, numbered in order, and opens that folder. Drag it onto your phone, a USB stick or your car's
drive, and it plays in order even in a player that ignores playlists. Or click **Make one file**: Radio Booth mixes
the show into a single MP3, crossfaded like the radio, with a chapter for each song and break. Some players, VLC among them, don't show MP3
chapters: open the `.cue` file next to the MP3 instead and they list every song and break. A 2-hour show
takes a few minutes to make. With Plex, both go into `Copies` in the `Radio Booth shows` folder in your home
folder (or in `BOOTH_SHOWS_FOLDER`, when that's set), and Radio Booth fetches the songs from your Plex server first.

If your account has a limit, your phone's Radio Booth page shows what's left above the form.

## 6. Tell us what you think

Once a show is in Plex, your phone's Radio Booth page shows **How was it?** under it. Tap it to give the show 1 to 5
stars and, if you like, a note. Below that are the show's breaks (the bits where the DJ talks), numbered the
same as in Plex. If the DJ got something wrong, said a name wrong, sounded off, or went on too long, tap
**Flag this break** and pick what happened. That's the most useful thing you can do for us: every rating and
flag is read.

For anything bigger, questions, or ideas, come say hi in the [Radio Booth Discord](https://discord.gg/aN2bNKB74y), where testers and
the people making Radio Booth talk.

## Make shows with your own AI assistant

If you use Claude, ChatGPT or Gemini, you can connect it to Radio Booth and make shows by chatting with it.
Your assistant already knows you and what you've talked about, so you can ask for something like "a two-hour
show for our drive up north tomorrow, with the songs my dad loved". It picks the songs from your library and
writes what the DJ says. Radio Booth then voices the DJ, in the voice you chose, and puts the show in Plex or
your shows folder like any other show. Radio Booth needs to be set up on your computer first (steps 1 to 4 above).

### Connect it

Add Radio Booth to your assistant as a custom connector, with this address (your phone's Radio Booth page shows it
too, under **Your assistant**):

```
https://my.radiobooth.fm/mcp
```

- **Claude** (on claude.ai or in the Claude app): open **Settings > Connectors**, click **Add custom
  connector**, name it `Radio Booth` and paste the address.
- **ChatGPT** or **Gemini**: add a custom connector (or app) in its settings with the same address. If it
  asks for a client ID or a client secret, leave them empty.

Your assistant then opens a Radio Booth page asking whether to allow it. Click **Allow**. That page uses your
Radio Booth sign-in: if it asks you to sign in, open your sign-in link in that same browser, then come back and
reload the page.

### Ask for a show

Just ask in a chat: "Make me a Radio Booth show for Sunday morning, an hour." Your assistant asks what it
needs (the length, the DJ and their voice), waits for Radio Booth on your computer to send your library, chooses
the songs and writes the breaks. That takes a few minutes of work on its side. Before it sends the show off,
ask to read the script: it can show you the whole show, song by song and break by break, and change what you
don't like. A few minutes after it sends it, the show is in Plex (or your shows folder), and it's listed on
your phone's Radio Booth page with your other shows, where you can rate it and flag breaks as usual.

- Shows your assistant makes don't count against your shows. It can make up to 10 a day.
- As with any show, the computer running Radio Booth needs to be on and awake.
- A show your assistant leaves unfinished for 3 hours is dropped. You can also cancel it on your phone's
  Radio Booth page, or ask your assistant to.
- If your assistant says a Radio Booth tool is missing or doesn't work after Radio Booth has been updated, turn the
  connector off and on again in its settings, so it picks up the new version.

### What your assistant can see

While it makes a show, your assistant can see your library's song list (titles, artists, albums, years,
genres, plays and the like, the same details Radio Booth sends for any show), the shows you've made, and the DJs.
Those details go to the AI service you use, under your own account with it. Radio Booth keeps your library's
details, encrypted, only while that show is being put together (at most 3 hours), and deletes them as soon as
the show is sent off, cancelled or dropped. Your music files stay on your computer, as always.

To disconnect your assistant, tap **Disconnect** next to it on your phone's Radio Booth page, under **Your
assistant**. It can't reach your Radio Booth from then on; to use it again, connect it again.

## Music on another computer

Your music is on a NAS, a media PC or another computer, and Radio Booth runs on a Windows PC or Mac in the same home.
Radio Booth reaches your music over your home network; nothing is opened to the internet.

### With Plex

Radio Booth reads your library from Plex over the network by itself. The one thing it needs is a folder for the DJ's
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

**On the computer running Radio Booth:**

1. **Connect to the shared folder and copy its path** (see [Copying a shared folder's path](#copying-a-shared-folders-path)).
2. **Download and open Radio Booth** and click **It's in Plex**, as in steps 2 to 4 above. Radio Booth notices that Plex
   runs on another computer, shows where the `Radio Booth` folder is there, and asks **where that same folder
   is from this computer**. Paste the path you copied.

If Radio Booth instead says to make a folder and a library, the `Radio Booth` library isn't in Plex yet (or has a
different name). Do the Plex side above, then try again.

### With a folder

1. **Connect to the shared folder your music is in, and copy its path** (see below).
2. **Click It's in a folder** on Radio Booth's page and paste it as your music folder.
3. **For the shows folder**, either keep the one Radio Booth suggests on this computer, or put it on the NAS too
   (for example a `Radio Booth shows` folder next to your music), so other computers and players at home can open
   the shows. Radio Booth writes playlists that work from any computer that sees the same folder.

The first read of a big collection over the network takes longer than from a local drive; Radio Booth shows a
progress bar, and after that it only reads what's new.

### Copying a shared folder's path

- **Windows:** in File Explorer, go to **Network**, then your NAS or other computer, then the folder. Hold
  **Shift**, right-click the folder and choose **Copy as path**. It looks like `"\\MyNAS\audio\Radio Booth"`.
  Use this kind of address rather than a drive letter like `Z:`, which may not be connected yet when Radio Booth
  starts.
- **Mac:** in Finder, choose **Go > Connect to Server**, type `smb://` and the NAS or computer's name (for
  example `smb://mynas.local`), and pick the shared folder. Then find the folder, hold **Option**, right-click
  it and choose **Copy "…" as Pathname**. It looks like `/Volumes/audio/Radio Booth`.

### Keep the shared folder connected

Radio Booth uses that folder for every show, so it must be connected whenever Radio Booth makes one. If it isn't, the show
says **Didn't work** on your phone; reconnect the folder and ask again.

- **Windows:** a `\\MyNAS\...` address reconnects by itself once your computer is signed in and on the
  network. If your NAS asks for a password, tick **Remember my credentials** the first time.
- **Mac:** shared folders don't reconnect by themselves after a restart. To make them, open
  **System Settings > General > Login Items**, click **+** under "Open at Login", and choose the shared
  folder (it's under **Locations** in the Finder sidebar while connected). If your Mac asks whether Radio
  Radio Booth may access files on a network volume, click **Allow**.

Both computers need to be at home, on the same network. A shared folder across the internet isn't supported.

## Sharing Radio Booth with someone in your home

Someone else with their own Radio Booth account can use your Radio Booth too, so they don't need Radio Booth on a computer
of their own. On Radio Booth's page, under **Settings**, click **Add another person**. On their phone, signed in to
their own account, they tap **Get a pairing code**; type that code into Radio Booth's page and click **Add**.

Their shows are made from the same music and go into the same Plex, with their name at the start of each
playlist (for example "Jennifer: Rainy drive home"). They count against their own show time, and Radio Booth keeps
a separate history for them, so their shows don't skip tracks just because they were in yours. They ask for
shows on their own phone, signed in as themselves. On Radio Booth's page, **Whose shows** under **Your shows** picks
whose shows are listed there.

To have their shows show up in their own Plex, pick their Plex user under **Share their playlists in Plex
with** next to their name. Radio Booth then shares each new playlist of theirs with them, and they find it in Plexamp
under **Shared Playlists**. They need to be able to see the **Radio Booth** library in Plex too, or the DJ's
breaks won't play for them; Radio Booth tells you if they can't. To stop, click **Remove** next to their
name. If they also run Radio Booth on a computer of their own, shows they ask for on their phone may go to either
one, so it's simplest to keep just one.

## Listening away from home

If it's switched on for you (testers, for now), each show that reached your computer has **Get the file** on
the phone page. Radio Booth, on the computer at home, mixes the show into one MP3 and sends it to your phone, which
takes a minute or two (the computer has to be on). Then tap **Download**. On an iPhone the file goes to
**Files › Downloads**; on Android, to **Downloads**. Radio Booth deletes its copy an hour after you download
it, or after a day if you don't.

## What Radio Booth sends, and what it doesn't

When you ask for a show, and only then, Radio Booth sends the details of your music library: titles, artists,
albums, years, genres, ratings, which of your Radio Booth shows had each song, and when songs turned up in
your library since you started using Radio Booth. That's what the DJ uses to pick songs and talk about them.
Radio Booth uses it to make that one show and doesn't keep it afterwards. (When your own AI assistant makes the show, your assistant sees those details
too, and Radio Booth keeps them, encrypted, until the show is finished: see
[What your assistant can see](#what-your-assistant-can-see).) While the show is made, the AI services that write and voice it (Claude, by
Anthropic, and Google Cloud's text-to-speech) process the parts they need, under business terms that don't
let them train on it.

Radio Booth does keep a short record of each show: what you asked for, its title, whether it reached Plex,
and what it cost to make.

Your music files never leave your computer, unless you ask to download a show on your phone: then that one
show, mixed into one MP3, goes up to Radio Booth for your phone to fetch, and Radio Booth deletes it an hour
after you download it (or after a day, if you don't). Radio Booth only ever connects out: to Plex, to Radio Booth, and to
GitHub to check for updates. Nothing on the internet, or on your home network, can connect in to your
computer through it. Radio Booth's page is shown only on the computer Radio Booth runs on.

The full details are in [`protocol/`](../protocol/).

## If something goes wrong

Open **Radio Booth** (Start menu, or Applications on a Mac) to see Radio Booth's page. The box at the top says what
Radio Booth is doing and, if something needs you, what to do.

- **The show stays at "Waiting for your computer".** Radio Booth isn't running, or the computer is asleep.
  Open **Radio Booth**; that starts it. Radio Booth's page should then say **On air**.
- **"Didn't work".** The reason is shown under the show. Try again; if it keeps happening, tell us in the
  [Discord](https://discord.gg/aN2bNKB74y) what it says, and what Radio Booth's page shows under **What Radio Booth has been doing**.
- **You want shows from another Plex library, changed your Plex setup, or moved your music.** On Radio
  Booth's page, click **Change** next to **Change Radio Booth's setup**, then **Change Plex library** (or
  **Change folders**), and pick the library. You don't need a new pairing code for this: your phone stays
  connected.
- **Radio Booth's page says "Radio Booth isn't running".** Open **Radio Booth** again.

## Updating Radio Booth

You don't need to: Radio Booth updates itself. Every few hours it checks for a new version, and installs it when
no show is on its way to Plex. Radio Booth's page shows which version you have, under **Settings**.

Anything else: ask in the [Radio Booth Discord](https://discord.gg/aN2bNKB74y), or get in touch with the person
who invited you.

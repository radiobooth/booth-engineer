<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="images/logo-horizontal-on-light.svg" width="280">
</picture>

# Getting started with Radio Booth

Radio Booth makes radio shows from your own music, with a DJ talking between songs. You ask for a show on
your phone ("Sunday morning coffee, an hour"), and a few minutes later it's a playlist in Plex.

This takes about 10 minutes, once.

## What you need

- **Plex Media Server with your music in it**, on a Windows PC or a Mac. Booth works best when it runs on
  that same computer. Plex on a NAS, a Linux machine or another computer? See
  [Other ways to set up Booth](other-setups.md).
- **Your phone**, with the sign-in link you were sent.
- That computer switched on and awake when you ask for a show. It doesn't need to stay on otherwise.

## 1. Sign in on your phone

Open the sign-in link you were sent, on your phone. You'll see your Booth page. Keep it handy: add it to
your home screen or bookmark it. The link is yours alone; please don't share it.

## 2. Download Booth on the Plex computer

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

**Plex.** Click **Sign in to Plex**. Plex's own sign-in page opens in a new tab: sign in and allow Radio
Booth. (Booth never sees your Plex password.) Then come back to Booth's tab. If you have more than one Plex
server or music library, click the one with your music.

Booth then adds a small library to Plex called **Radio Booth**. The DJ's voice clips go there, so they never
mix into your own music.

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
**Playlists**.

If your account has a limit, both pages show what's left above the form.

## 6. Tell us what you think

Once a show is in Plex, your phone's Booth page shows **How was it?** under it. Tap it to give the show 1 to 5
stars and, if you like, a note. Below that are the show's breaks (the bits where the DJ talks), numbered the
same as in Plex. If the DJ got something wrong, said a name wrong, sounded off, or went on too long, tap
**Flag this break** and pick what happened. That's the most useful thing you can do for us: every rating and
flag is read.

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

## What Booth sends, and what it doesn't

When you ask for a show, and only then, Booth sends the details of your music library: titles, artists,
albums, years, genres, ratings, play counts, when you added things, and which songs were in your recent
shows. That's what the DJ uses to pick songs and talk about them. Radio Booth uses it to make that one show
and doesn't keep it afterwards. While the show is made, the AI services that write and voice it (Claude, by
Anthropic, and Google Cloud's text-to-speech) process the parts they need, under business terms that don't
let them train on it.

Radio Booth does keep a short record of each show: what you asked for, its title, whether it reached Plex,
and what it cost to make.

Your music files never leave your computer. Booth only ever connects out: to Plex, to Radio Booth, and to
GitHub to check for updates. Nothing on the internet, or on your home network, can connect in to your
computer through it. Booth's page is shown only on the computer Booth runs on.

The full details are in [`protocol/`](../protocol/).

## If something goes wrong

Open **Radio Booth** (Start menu, or Applications on a Mac) to see Booth's page. The box at the top says what
Booth is doing and, if something needs you, what to do.

- **The show stays at "Waiting for your Booth Engineer".** Booth isn't running, or the computer is asleep.
  Open **Radio Booth**; that starts it. Booth's page should then say **On air**.
- **"Didn't work".** The reason is shown under the show. Try again; if it keeps happening, tell us what it
  says, and what Booth's page shows under **What Booth has been doing**.
- **You changed your Plex setup, or moved your music.** On Booth's page, click **Change** next to
  **Change Booth's setup**, then **Sign in to Plex again**.
- **Booth's page says "Booth isn't running".** Open **Radio Booth** again.

## Updating Booth

You don't need to: Booth updates itself. Every few hours it checks for a new version, and installs it when
no show is on its way to Plex. Booth's page shows which version you have, under **Settings**.

Anything else: get in touch with the person who invited you.

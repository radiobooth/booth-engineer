# Getting started with Radio Booth

Radio Booth makes radio shows from your own music, with a DJ talking between songs. You ask for a show on
your phone ("Sunday morning coffee, an hour"), and a few minutes later it's a playlist in Plex.

This takes about 10 minutes, once.

## What you need

- **Plex Media Server with your music in it**, on a Windows PC or a Mac. Booth works best when it runs on
  that same computer.
- **Your phone**, with the sign-in link you were sent.
- That computer switched on and awake when you ask for a show. It doesn't need to stay on otherwise.

## 1. Sign in on your phone

Open the sign-in link you were sent, on your phone. You'll see your Booth page. Keep it handy: add it to
your home screen or bookmark it. The link is yours alone; please don't share it.

## 2. Download Booth on the Plex computer

Go to the [latest release](https://github.com/radiobooth/booth-engineer/releases/latest) and download:

- **Windows:** `RadioBooth-Windows.exe`
- **Mac:** `RadioBooth-macOS.zip`, then double-click it to unzip. You get `Radio Booth.command`. It
  needs a Mac with Apple silicon (M1 or later); for an older Intel Mac, ask the person who invited you.

## 3. Open it

**Windows:** double-click `RadioBooth-Windows.exe`. Windows may show a blue box saying "Windows protected
your PC", because Booth is new and not yet known to Microsoft. Click **More info**, then **Run anyway**.

**Mac:** double-click `Radio Booth.command`. If your Mac says it can't check the app for malicious
software, open **System Settings > Privacy & Security**, scroll down, click **Open Anyway** next to
"Radio Booth.command", and confirm.

A window with text opens. That's Booth. It asks a few things; type your answer and press Enter.

## 4. Follow the three steps

**Plex.** Your browser opens Plex's own sign-in page. Sign in and allow Radio Booth. (Booth never sees your
Plex password.) If you have more than one Plex server or music library, Booth asks which one by number.

Booth then adds a small library to Plex called **Radio Booth**. The DJ's voice clips go there, so they never
mix into your own music.

**Your Booth account.** On your phone's Booth page, tap **Get a pairing code**. Type the code into the
Booth window. It works once and lasts 10 minutes.

**Start automatically.** Press Enter to say yes. Booth then starts by itself whenever you sign in to the
computer:

- **Windows:** in a small window on the taskbar. Leave it open; closing it stops Booth until next time.
  You'll also find **Radio Booth** and **Radio Booth setup** in the Start menu.
- **Mac:** quietly in the background.

That's it.

## 5. Ask for a show

On your phone, describe the show, pick a length and a DJ, and tap **Make the show**. The page tells you how
it's going. When it says **In Plex**, open Plex and look under **Playlists**.

Your shows count against a weekly amount of show time, which your Booth page shows above the form.

## What Booth sends, and what it doesn't

When you ask for a show, and only then, Booth sends the details of your music library: titles, artists,
albums, years, genres, ratings, play counts, when you added things, and which songs were in your recent
shows. That's what the DJ uses to pick songs and talk about them. Radio Booth uses it to make that one show
and doesn't keep it afterwards. While the show is made, the AI services that write and voice it (Claude, by
Anthropic, and Google Cloud's text-to-speech) process the parts they need, under business terms that don't
let them train on it.

Radio Booth does keep a short record of each show: what you asked for, its title, whether it reached Plex,
and what it cost to make.

Your music files never leave your computer. Booth only ever connects out to Plex and to Radio Booth;
nothing on the internet can connect in to your computer through it.

The full details are in [`protocol/`](../protocol/).

## If something goes wrong

- **The show stays at "Waiting for your Booth Engineer".** Booth isn't running, or the computer is asleep.
  On Windows, open **Radio Booth** from the Start menu. On a Mac, double-click `Radio Booth.command` again.
  If Booth can't start because something needs setting up again, it says so and offers to do it: press
  Enter.
- **"Didn't work".** The reason is shown under the show. Try again; if it keeps happening, tell us what it
  says.
- **You changed your Plex setup, or moved your music.** On Windows, run **Radio Booth setup** from the
  Start menu. On a Mac, double-click `Radio Booth.command`; it says Booth is already running and asks if
  you want to change its settings. Type `y` and press Enter.
- **"Booth is already running on this computer."** That's fine: it's already on, in another window or in
  the background. Press Enter to close this window.

Anything else: get in touch with the person who invited you.

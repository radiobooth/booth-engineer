# What's new in Radio Booth

Each release's notes come from its section here (the release workflow refuses a version without one). Write
for listeners: what they'll notice, in plain words. Newest first. Keep each change one `- ` bullet (wrapped
lines indented): that's what Radio Booth's page shows under "What's new".

## 0.5.8 (2026-11-27)

- **It's called Radio Booth everywhere now.** The app's page, its messages, the setup guide and the help
  for the `booth` command say "Radio Booth" instead of just "Booth". Nothing else changes: your settings
  and your shows stay where they are.
- **New installs keep shows in a "Radio Booth shows" folder.** If you already have a "Booth shows" folder,
  Radio Booth keeps using it, so your copies and one-file shows stay put. Rename it yourself if you like:
  quit Radio Booth, rename the folder, and open Radio Booth again (with your music in a folder, also pick
  the renamed folder under Settings).

## 0.5.7 (2026-11-25)

- **You can remove a computer from your Radio Booth.** On your phone, your Booth page lists your computers
  with a **Remove** button, for a lost or sold computer or an old install. A removed computer's Booth page says
  "This computer was removed from your Radio Booth" and asks for a new pairing code, so you can connect it
  again whenever you like.
- **Booth waits while Plex is still reading your music.** If you ask for a show while Plex is still adding a new
  music library, Booth now waits for it instead of giving up after half a minute, and your phone says "Plex
  is still reading your music library". After 10 minutes it makes the show from the songs Plex has read so
  far. If Plex has none ready after 45 minutes, the show stops and says why, so you can ask again once Plex
  is done. Plex checking a library it already knows for new music doesn't hold shows up.

## 0.5.6 (2026-11-24)

- **Shows are made on your phone now, and only there.** Booth's page on the computer no longer has its own New
  show form, so there's one place to ask for a show. In its place is a big **Make a show on your phone** card
  with a QR code: scan it with your phone's camera to open your Booth page, or click **Open it here** to use it
  on the computer.
- **Rate shows and flag breaks on your phone.** "How was it?" has moved off Booth's page on the computer too.
- Your latest shows are still listed on Booth's page under **Your shows**, with **Make one file**, **Copy to a
  folder** and **Remove**.

## 0.5.5 (2026-11-24)

- **A music library Booth can't use no longer leaves shows waiting.** If Booth finds no songs it can use in your
  library (it's empty, Plex is still adding your music, or the songs lack a title, artist or length), the show
  now stops after a few tries and says so, instead of waiting an hour. Your next show isn't held up behind it.

## 0.5.4 (2026-11-22)

- **Updates on Windows tell you when they fail.** If "Update now" can't finish, Booth's page now says why and
  offers "Try again", instead of quietly staying on the old version. It also gets past a leftover old copy of
  Booth that Windows had marked read-only, which stopped some updates altogether.
- **What's new, before you update.** When a new version is out, Settings shows what changed in it next to
  "Update now". (You'll see this from the next version on.)
- **"Update now" during a show** waits for the show to finish, then installs.
- **Plex on another computer:** if setup was given the shared folder one level above the one Plex watches,
  Booth now finds the right folder for its breaks by itself.
- **Help is on Discord.** The setup guides now link to the Radio Booth Discord.
- Booth's log no longer fills with error text when its page gives up waiting on a slow answer.

## 0.5.3 (2026-11-21)

- **Big Plex libraries:** Booth now reads a library even when a few song tags are damaged (odd characters in a
  title, say). Before, one bad tag could stop a show at "Waiting for Booth".
- If a library really can't be read, the show now fails after three tries with a clear message, so your next
  show isn't held up behind it.

## 0.5.1 (2026-11-20)

- **Windows:** turning on "Start when I log in" works again. It had stopped with "Close the Booth window", when
  there was no window to close.

## 0.5.0 (2026-11-19)

- **Download a show to your phone.** On your phone's Booth page, "Get the file" asks Booth at home to make the
  show into one MP3 with chapters and send it to your phone, for listening offline or in the car. Only the
  show you asked for is sent, only when you ask, and it's deleted from our side soon after you download it.
  Your Booth DJ account needs this switched on.

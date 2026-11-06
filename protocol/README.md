# Protocol

JSON schemas for everything Booth Engineer exchanges with the Booth DJ service, and the
[API](api.md) it uses to exchange them. They live in this public
repo so anyone can read exactly what leaves your machine. Version 0: expect changes until the pilot.

| Schema | Direction | What it is |
|---|---|---|
| [`catalog`](catalog.schema.json) | your machine → service | Track metadata: title, artist, album, year, genres, length, when you added it (left out for tracks that came in with a bulk import, such as your server's first scan), play count and rating if your server has them, sonic analysis if your server has it, and when each track was last in one of your Booth shows. |
| [`show-request`](show-request.schema.json) | you → service | The prompt, show length, DJ (personality, voice, your name for them) and your station name. |
| [`show-package`](show-package.schema.json) | service → your machine | The running order: your track ids and the DJ breaks between them, each break with its audio file, transcript and fact sources. |

The catalog is sent only when you ask for a show, and Booth DJ never stores it.

Your show history (which tracks were in which delivered show, so new shows don't repeat them) is kept by
Booth Engineer on your machine, in `history.json` next to its config file. It travels only inside the
catalog, as each track's `last_in_show_at`, so Booth DJ forgets it along with the catalog. Delete the file
to start the history over.

What never leaves your machine: audio, file paths, your music server's address or token. Track ids are
opaque; Booth Engineer maps them back to files locally.

Rules the schemas can't express:

- Track ids in a catalog are unique.
- Every `track_id` in a show package exists in the catalog the show was made from.
- Break ids and files in a show package are unique, and `sha256` is the hash of that file.

Examples are in [`examples/`](examples/) and are checked by the test suite.

## Plex sign-in during setup

`booth setup` also talks to Plex's own account service, plex.tv, and to nothing else beyond your Plex
server and Booth DJ. It asks plex.tv for a sign-in code (sending only Booth's name and a random id for this
install), waits while you sign in on Plex's page, and then lists the Plex servers your account owns, to find
yours. Your Plex token is saved only in Booth Engineer's local config file. Nothing from your library goes
to plex.tv.

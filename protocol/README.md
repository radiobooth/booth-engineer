# Protocol

JSON schemas for everything Booth Engineer exchanges with the Booth DJ service, and the
[API](api.md) it uses to exchange them. They live in this public
repo so anyone can read exactly what leaves your machine. Version 0: expect changes until the pilot.

| Schema | Direction | What it is |
|---|---|---|
| [`catalog`](catalog.schema.json) | your machine → service | Track metadata: title, artist, album, year, genres, length, when you added it, play count and rating if your server has them, sonic analysis if your server has it. |
| [`show-request`](show-request.schema.json) | you → service | The prompt, show length, DJ (personality, voice, your name for them) and your station name. |
| [`show-package`](show-package.schema.json) | service → your machine | The running order: your track ids and the DJ breaks between them, each break with its audio file, transcript and fact sources. |

The catalog is sent only when you ask for a show, and Booth DJ never stores it.

What never leaves your machine: audio, file paths, your music server's address or token. Track ids are
opaque; Booth Engineer maps them back to files locally.

Rules the schemas can't express:

- Track ids in a catalog are unique.
- Every `track_id` in a show package exists in the catalog the show was made from.
- Break ids and files in a show package are unique, and `sha256` is the hash of that file.

Examples are in [`examples/`](examples/) and are checked by the test suite.

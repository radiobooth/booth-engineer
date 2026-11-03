# Protocol

JSON schemas for everything Booth Engineer exchanges with the Booth DJ service. They live in this public
repo so anyone can read exactly what leaves your machine.

- `catalog`: track metadata only (title, artist, album, year, genre, date added, track id, server path,
  sonic data if your server has it). Never audio.
- `show-request`: the prompt, length, DJ and voice.
- `show-package`: the breaks (audio files) and the ordered playlist of your track ids and breaks.

Version 0 of the schemas comes in the next change.

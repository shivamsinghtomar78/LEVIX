# Music

`levix music` plays, inspects and queues **local audio** natively: decoding is
libsndfile (bundled inside the `soundfile` wheel), output is PortAudio (bundled
inside `sounddevice`). There is **no ffmpeg anywhere in this module** - a codec
libsndfile does not carry is reported as missing, never faked, and nothing
shells out (`src/levix/modules/music/core.py`).

Requires the `music` extra (`pip install "levix[music]"`; soundfile >= 0.14,
sounddevice >= 0.5). Without it every subcommand exits **3** with that line.
`levix music -h`, `playlist` bookkeeping and `library` need no PortAudio;
sounddevice is imported only inside the hardware seam `core.play_samples` /
`core.list_devices`.

Headphones or modest volume are wise: `--volume`/`music.volume` is capped at
1.0 by `core.validate_volume` (values above/below 0.0-1.0, or non-numeric, are
`ConfigError` -> exit **5**), and samples are clamped, not wrapped, so gain
never produces digital distortion past full scale. LEVIX makes no system audio
changes: it never sets OS volume, never installs drivers, and closes the stream
on every path including Ctrl+C.

## Commands

### `levix music play FILE`

Decode one file with libsndfile and play it on an output device.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--device N` | `-1` | Output device index; -1 = PortAudio's default output |
| `-r`, `--rate Hz` | `0` | Resample to this rate (8000-192000 validated); 0 = the file's own rate. Method is honest: linear interpolation, not windowed sinc |
| `-v`, `--volume X` | `-1.0` (= "use config") | 0.0-1.0; `music.volume` config default is 0.8 |
| `--block N` | `0` | Frames per audio callback; 0 = the device's preference |

Prints the file line (`name  FORMAT/SUBTYPE  Hz  channels  length  gain`), the
codec note ("uncompressed samples, decoded natively by libsndfile" or the
named compressed codec, decoded in-process), a live bar on a TTY, then
`done N frames (...) at Hz`.

### `levix music info FILE`

Sample rate, channels, frames, duration, format/subtype, file size, and the
**decoder honesty line**: which soundfile and which libsndfile version are
actually doing the work (`core.decoder_version()`). Exit **7** with the codec
name for files libsndfile cannot read (m4a/mp4/aac/wma/mka/mkv/ape/midi); exit
**2** for a missing file or a directory.

### `levix music devices [--kind all|output|input]` (default `all`)

Every device PortAudio reports, *including the ones it cannot use*: index, name
(clipped with ASCII, never U+2026), host API, input/output channel counts,
default rate, role, and which index is the default in/out. When nothing has
output channels it says "no device with output channels: playback cannot start
on this machine", and when PortAudio reports no default it says "pass --device N
from the list" - exit stays 0; the listing itself succeeded. An unknown
`--kind` is exit 2.

### `levix music library [--root DIR] [--suffix EXT] [--limit N] [--include-hidden]`

Walk `music.library_dir` (config, default empty) or `--root` and report what
can **actually be decoded**, by asking libsndfile about each candidate.

- Scanned suffixes: `.wav .flac .ogg .opus .mp3 .aiff .aif .au`.
- Defaults: `--limit 25` rows (`0` = all), hidden entries skipped unless
  `--include-hidden`, `--suffix` repeatable to narrow the set.
- Prints a track table, per-directory totals, then honest counts: tracks,
  total duration, folders walked, files examined, files of another type.
  Files that looked like audio but did not decode are named (up to 8, then a
  "more" count) - never dropped silently.
- Nothing configured anywhere: it prints "music.library_dir is not set, so
  there is nothing to scan." with the two ways to fix it, and exits 0.
- `music.library_dir` set but not a readable directory -> exit **5**; a `--root`
  that does not exist / is not a directory -> exit **2**.

### `levix music playlist list | add FILE... | remove ID... | clear [--yes] | play [flags]`

The queue lives in the **shared LEVIX SQLite database** (`levix.db`), table
`music_playlist` (`id`, `path` UNIQUE, `added_at` UTC stamp), under the
`music` migration namespace. The migration is registered at runtime by
`core.ensure_schema` filling the empty `music` slot of `storage.MIGRATIONS`, so
`_levix_schema` stays truthful for `levix doctor` instead of the module running
unrecorded DDL.

- `list`: rows in play order with a state column - an entry whose file went
  missing is flagged `missing`, not hidden.
- `add`: every name is validated as a real file **before** anything is stored;
  a batch containing a ghost queues nothing at all; duplicates are reported with
  `=` and skipped.
- `remove`: stale ids are reported ("no playlist row with id N"), not fatal.
- `clear`: destructive - goes through `levix approve.require_approval`
  (`destructive=True`): you must type the word; `--yes` is explicitly refused
  and cannot authorise it; with no TTY on stdin it refuses at exit **6** and
  forgets nothing. The files on disk are never touched, only the rows.
- `play`: plays the queue in order with the same flags as `music play`; an
  entry that cannot be decoded is skipped with a one-line warning and the queue
  continues; ends with `done X played, Y skipped of Z`.

## Reporting rules

File names come from disk, device names from PortAudio - both untrusted text.
Every dynamic value passes `cli._show` = markup `escape` + `core.safe_text`
(cp1252-safe backslash replacement), so `[live]` in a real filename prints
literally instead of being eaten as a style tag, and a non-Latin device name
cannot crash the table. `_clip` truncates with ASCII `+`.

## Exit codes

| Code | Meaning here |
|---|---|
| 2 | Missing file, directory-as-file, bad `--root`, bad `--rate`, bad `--kind`, stale usage |
| 3 | `music` extra not installed |
| 5 | Volume or `music.library_dir` config value invalid |
| 6 | `playlist clear` declined or no terminal to confirm in |
| 7 | libsndfile refused the file (`UnsupportedFormatError`) or PortAudio could not open/drive a stream (`AudioDeviceError`) - one clean message, hint names `levix music devices` |
| 130 | Ctrl+C during playback; "the stream closed, so the device is free" |

## Tests

`tests/modules/test_music.py` - 57 test functions, 74 collected cases on Windows.
Design: `core.play_samples` is the
only function touching PortAudio, so command tests monkeypatch that one name and
assert on the frames handed to the seam; **no unit test opens a stream**, which
is what lets the suite run sound-card-free. Audio fixtures are real bytes
written by soundfile (WAV/FLAC/OGG/MP3), so decoding runs against genuine
libsndfile parses, not mocks. Covered: gain/clamp math and volume validation,
rate validation and resample length/clock, duration formatting, decode verdicts
including "undecodable exits 7 and names the decoder", play through the seam
with device/rate/volume/config precedence, exit codes (5 bad volume, 2 bad rate,
130 on simulated KeyboardInterrupt, 7 on backend refusal), device table roles
and defaults and bad `--kind`, library scan (real tracks, refused files named,
per-folder totals, hidden opt-in, suffix narrowing, unset root says so, vanished
config root is a config error), playlist migration namespacing/idempotency,
add-duplicate-ghost semantics, remove/clear/list, clear needing a terminal
(exit 6) with files untouched, playlist play skipping broken entries, manifest
contract, and subprocess proof that help does not import sounddevice/soundfile.
The single `@pytest.mark.integration` test really plays 0.05 s of a tone on a
real output device and **skips out loud** if PortAudio reports no usable device.
Not covered: decode paths for `.opus`, `.aiff`, `.aif`, `.au` (they are scan
candidates but no fixture writes them), and true simultaneous-device behaviour.

## Known gaps

1. **The whole file is decoded into memory before playback starts.** `core.load` calls
   `soundfile.read(..., dtype="float32", always_2d=True)`
   (`src/levix/modules/music/core.py:298-307`), so the array handed to PortAudio is
   `frames x channels x 4` bytes at full resolution: a 90-minute 24-bit/96 kHz stereo file is
   about 3.1 GB of RAM on top of the file itself. There is no streaming decode and no
   chunk-and-refill loop, so on an 8 GB machine such a file is refused by the OS, not by a
   LEVIX message. `levix music info FILE` is the safe way to look before playing.
2. **Downsampling aliases.** `core.resample` is `np.interp` per channel
   (`core.py:343-362`) - linear interpolation, exactly as the flag help says - so `--rate`
   from 96 kHz to 44.1 kHz folds the band above 22 kHz down instead of filtering it out. Fine
   for checking a file sounds right, wrong for anything measured. No anti-alias filter is
   applied and none is planned here.
3. **Codecs libsndfile does not carry are refused, not transcoded.** `.m4a .mp4 .aac .wma
   .mka .mkv .ape .mid .midi` are named in `core.MISSING_CODECS` (`core.py:42-52`) and exit 7
   with "re-encode to WAV, FLAC, OGG or MP3", because LEVIX never calls ffmpeg. A large part
   of what people keep on disk is `.m4a`, so this is the module's most visible limit.
4. **No transport controls.** There is no pause, seek, resume or skip while a file plays;
   the only interaction is Ctrl+C, which closes the stream and exits 130. A long file started
   by accident runs to wherever Ctrl+C lands it, and nothing remembers a position.
5. **The playlist is insertion order, permanently.** `core.list_playlist` ends with
   `ORDER BY id` (`core.py:641-647`) and there is no move/reorder/shuffle/repeat command -
   `remove ID` and `add FILE...` are the only edits, so building a running order means
   clearing and re-adding.
6. **No tags at all.** `core.AudioInfo` carries `path, samplerate, channels, frames,
   duration, format, subtype` (`core.py:113-120`) and nothing else, so `info` and `library`
   cannot show title, artist, album, track number or cover art. Reading those needs a tag
   library (mutagen or equivalent) that this module deliberately does not depend on.
7. **One stream at a time, per process.** `core.play_samples` opens a PortAudio stream for
   the call and closes it on every exit path, so two `levix music play` processes compete for
   the device and there is no cross-device simultaneous output. Whether PortAudio's shared
   mode makes that a click, a mix or a refusal is not verified here.

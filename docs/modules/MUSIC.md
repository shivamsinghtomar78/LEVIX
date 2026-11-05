# Music

`levix music` plays, inspects and queues audio **natively**: decoding is
libsndfile (bundled inside the `soundfile` wheel), output is PortAudio (bundled
inside `sounddevice`). **For a local file there is no ffmpeg in the path at all** - a
codec libsndfile does not carry is reported as missing, never faked, and nothing
shells out (`src/levix/modules/music/core.py`). One source is the exception and says
so: an `http(s)` URL is fetched by yt-dlp and converted by ffmpeg, both imported only
when a URL was actually passed - see §Playing a URL.

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

### `levix music play SOURCE`

Decode one audio file - or one stream fetched from an `http(s)` URL - and play it on an
output device. Which kind of source it is comes from the scheme, and a `file:` URL is
refused rather than read. `core.is_url` asks for **two characters** of scheme, which is
what keeps `C:\music\tone.wav` a path (`urlsplit` reads that drive letter as the scheme
`c`); the trade is a POSIX file literally named `mix:1.wav`, which reads as a link, so name
it `./mix:1.wav`.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--device N` | `-1` | Output device index; -1 = PortAudio's default output |
| `-r`, `--rate Hz` | `0` | Resample to this rate (8000-192000 validated); 0 = the file's own rate. Method is honest: linear interpolation, not windowed sinc |
| `-v`, `--volume X` | `-1.0` (= "use config") | 0.0-1.0; `music.volume` config default is 0.8 |
| `--block N` | `0` | Frames per audio callback; 0 = the device's preference |
| `--visual bar\|off` | `music.visual`, built-in `bar` | Draw the spectrum while sound plays; `off` keeps the single-line progress bar |

Prints the source line (`name  FORMAT/SUBTYPE  Hz  channels  length  gain`), the
codec note ("uncompressed samples, decoded natively by libsndfile" or the
named compressed codec, decoded in-process), a live bar on a TTY, then
`done N frames (...) at Hz`. For a URL the source line names **the link that was
pasted**, not `audio.mp3`, because the cache name describes this machine and says nothing
about the song.

#### Playing a URL

`levix music play "https://www.youtube.com/watch?v=…"` asks yt-dlp for the best
audio-only stream, converts it with ffmpeg, and hands the result to the same
libsndfile decode path a local file uses. The rules and the reason for each:

- **Two things must be installed that a local file never needs.** `yt_dlp` comes from
  `levix[tube]` - Music does not own it, so its absence is exit **3** with that exact
  hint - and `ffmpeg` must be on `PATH`, named by `install_command_for()` for *this*
  platform (the same table Tube keeps, guarded against drift by a test). The ffmpeg half is
  not a nicety. Measured with yt-dlp `2026.10.26` and libsndfile `1.2.2`: an audio-only
  stream pulled without a postprocessor lands as `.m4a`, and `soundfile.info` answers
  `Format not recognised`; with `FFmpegExtractAudio(preferredcodec="mp3")` the same call
  reports `MP3/MPEG_LAYER_III 44100 Hz 2 ch`, which decodes. So the URL path uses ffmpeg
  and the file path still never touches it - and LEVIX builds no ffmpeg command line: the
  conversion happens inside yt-dlp's postprocessor.
- **Nothing the remote side chose names a file on this disk.** The cache path is
  `sha256(url)`-derived (`<cache_dir>/streams/<16 hex>/audio.mp3`, `core.stream_target`),
  never the title, and the path yt-dlp reports back is checked to resolve inside that
  directory before anything opens it (`_reported_path`): a report from elsewhere is exit
  **7** and nothing is read. Titles are arbitrary text from a server; a filename is not
  allowed to be.
- **The same URL does not fetch twice.** If the cached `audio.mp3` exists the network is
  not touched, so a link replays offline - with no yt-dlp and no ffmpeg either, since the
  gate is only reached on the branch that needs them - and nothing prunes that cache
  (gap 9). `core.needs_fetch` is the same question the CLI asks before it warns you about
  the wait: "asking yt-dlp … this is quiet until the audio has landed" appears only in
  front of a download that is really about to happen, never for a cached link, a refused
  scheme or a plain path.
- **One item per call.** `noplaylist` is always set; a playlist is Tube's job and the
  refusal says `levix tube download --playlist`.
- **`file:` and every other scheme are refused** with exit **2**, and the scheme is judged
  *before* either tool is looked for, so a link this command will not fetch is never
  reported as a missing dependency. `enable_file_urls` is deliberately never set - the same
  position `tube.core.build_options` takes: a URL copied from somewhere else must not get
  this process to read this disk.
- **A fetch has a byte cap.** `STREAM_MAX_BYTES` (128 MiB, 134,217,728 bytes) goes to
  yt-dlp as `max_filesize`, and the file that landed is measured against the same number
  before it is decoded - because `max_filesize` only fires when the server *declared* a
  length (yt-dlp's HTTP downloader compares it against `data_len`), so an unknown-length
  answer needs the on-disk check. Over the cap is exit **7**. See gap 10 for what the cap
  does and does not protect.
- **yt-dlp writes nothing this module did not print.** Its `logger` option is set to a
  sink with the three documented methods, so its own `ERROR: …` line does not appear above
  LEVIX's message: with `ignoreerrors` False, every error yt-dlp reports also raises, and
  that exception is what `fetch_audio` maps - to exit **8** (a network-side failure), with
  the tool's own reason quoted inside the one message, in `safe_text` so a cp1252 console
  cannot crash on it.
- **It is a fetch, not a workaround.** LEVIX adds no DRM handling, no cookie or login
  support, and no bulk harvesting; the user pasted one link and asked for that link. The
  copyright and ToS statement lives in `docs/modules/TUBE.md` and applies here unchanged.

#### The spectrum

Bars, not a plot: one column per log-spaced band, drawn from the audio at the playhead.

- The playhead is the only new plumbing. `core.play_samples` already reports
  `(frames_delivered, total)` from its PortAudio callback - `on_block`, which the existing
  progress line has used for three releases - and the visualiser was handed the same
  array, so it reads the last `window` frames before the playhead and draws those. No
  second thread, no new seam into PortAudio.
- The math is pure and in `music/visual.py`: `band_edges`, `band_bins`, `levels_from`,
  `spectrum`, `apply_caps` and `frame_due`. None of them imports Rich or a device, and only
  `spectrum` asks for numpy, which is what lets the suite assert on a 440 Hz tone instead of
  watching a screen.
- A column is **0 dBFS at the top and -54 dBFS at the floor** (`CEIL_DB`/`FLOOR_DB`), each
  band showing its loudest bin. The first version of this file mapped -80 to -18 dBFS and
  measured a full mix at 0.75-1.0 in every band: a solid block, not a meter. The wider
  ceiling is what puts the movement in the middle of the rows.
- The window is 40 Hz-15 kHz, log-spaced, and content outside it is not drawn: a 21 Hz
  sub-rumble and a 17 kHz tone both leave the meter at the floor. `band_count` cuts the
  columns to what the terminal has room for, at most 24.
- A band narrower than one FFT bin holds no bin centre - at 44.1 kHz over the 2048-frame
  window that is exactly true of 65.5-83.9 Hz, and reading centres alone left that column
  dark through every bass note. `band_bins` therefore hands each band every bin that comes
  within half a bin of it, so a low band can share its neighbour's energy, the way a filter
  with a slope does. The mapping depends only on rate, window and column count and is
  cached: the alternative was a ~1000-bin Python scan inside the audio callback, which
  measured 1.68 ms a frame against 0.11 ms for the cached version.
- The drawing is `Live(auto_refresh=False)` driven by `frame_due`, the discipline
  `hacker matrix` already uses: the loop owns the clock, the rate is bounded, and a
  redirected stream gets no escape sequences at all. The first frame comes from the first
  callback, not from `start()`: drawing in `start()` stamps the clock and the gate then
  swallows the only callback a short file gets.
- Block glyphs come from `terminal.active_glyphs()` (`█`, ASCII `#` fallback), because a
  cp1252 Windows console raises `UnicodeEncodeError` inside Rich's writer on U+2588.
- Off a terminal, the *default* quietly keeps the existing one-line progress bar; an
  explicit `--visual bar` on a pipe is refused with exit **2** and names `--visual off`,
  because silently ignoring a flag the user typed is worse than refusing it.

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
| 2 | Missing file, directory-as-file, bad `--root`, bad `--rate`, bad `--kind`, bad `--visual`, a URL whose scheme is not `http`/`https`, stale usage |
| 3 | `music` extra not installed; or a URL was passed and `yt_dlp` (from `levix[tube]`) or `ffmpeg` is not available |
| 5 | Volume or `music.library_dir` config value invalid |
| 6 | `playlist clear` declined or no terminal to confirm in |
| 7 | libsndfile refused the file (`UnsupportedFormatError`), PortAudio could not open/drive a stream (`AudioDeviceError`), or the fetched stream was refused before it was opened (path outside the URL's own folder, bytes over `STREAM_MAX_BYTES`) - one clean message, hint names `levix music devices` for the audio half |
| 8 | yt-dlp could not fetch the link: page gone, connection refused, or no file path reported. `fetch_audio` maps the tool's exception, quoting its own reason, and yt-dlp's duplicate line is swallowed by the logger it is given |
| 130 | Ctrl+C during playback; "the stream closed, so the device is free" |

## Tests

`tests/modules/test_music.py` - 104 test functions, 155 collected cases on Windows.
Design: two names are the replaceable points. `core.play_samples` is the only
function touching PortAudio and `core._make_ydl` the only one importing yt-dlp, so
command tests monkeypatch those and assert on the frames handed to the seam and the
options handed to the fetch; **no unit test opens a stream and none contacts a
network**, which is what lets the suite run sound-card-free and offline. Audio
fixtures are real bytes written by soundfile, and one parametrised test writes
*every* container the library scan offers - WAV/PCM_16, FLAC, OGG/VORBIS, OGG/OPUS,
MP3/MPEG_LAYER_III, AIFF under both `.aiff` and `.aif`, and AU - next to a guard that
the table equals `core.SCAN_SUFFIXES`, so adding a suffix to the scan without proving
it decodes fails the suite. `.opus` and `.aif` name no format to soundfile and Opus
takes only 8/12/16/24/48 kHz, which is why that table carries the write arguments.
The URL fake writes a genuine MP3 into the folder `fetch_audio` told it to use, so
the decode path still runs against real libsndfile parses: what is replaced is the
network and the converter, never the decoder.

Covered: gain/clamp math and volume validation, rate validation and resample
length/clock, duration formatting, decode verdicts including "undecodable exits 7 and
names the decoder" and "every scanned container decodes here", play through the seam
with device/rate/volume/config precedence, exit codes (5 bad volume, 2 bad rate,
130 on simulated KeyboardInterrupt, 7 on backend refusal), device table roles
and defaults and bad `--kind`, library scan (real tracks, refused files named,
per-folder totals, hidden opt-in, suffix narrowing, unset root says so, vanished
config root is a config error), playlist migration namespacing/idempotency,
add-duplicate-ghost semantics, remove/clear/list, clear needing a terminal
(exit 6) with files untouched, playlist play skipping broken entries, the spectrum
rules as pure numbers (which band a tone lights, the band with no bin centre, the
dBFS mapping, the meter range, silence and full scale, log spacing, columns versus
terminal width, the frame gate, the rows drawn, the colours, stereo and mono
measuring the same, a low rate stopping at its own Nyquist) and the visual through
the same seam, the manifest contract, and subprocess proof that help does not import
sounddevice/soundfile.

The URL half covers: what counts as a link (the two-character scheme rule, so
`C:\music\tone.wav`, `./mix:1.wav` and `~/Music/tone.wav` stay paths while `file:` and
`magnet:` read as links), a link fetched and played through the real CLI with **the
pasted URL** - not `audio.mp3` - on the source line, the exact option set read back
from the seam (`ba/b`, `noplaylist`, `outtmpl`, `max_filesize`, the ffmpeg
postprocessor, `paths.home`, and `enable_file_urls` absent), the logger being a silent
sink on all three documented methods, the cache folder derived from `sha256(url)` so
nothing a server chose names anything on this disk, a second link getting its own
folder, a replay that never builds a second yt-dlp, the wait notice appearing only in
front of a download that is really about to happen, a refused scheme resolved before
either tool or the cache is looked at, a reported path outside the URL's own folder
refused and never decoded (exit 7), a fetch that reports no path (exit 8), yt-dlp
raising into one mapped message quoting its own reason (exit 8), a file already on
disk over the byte cap refused before decode (exit 7, exact bytes named, and no
download attempted), missing `yt_dlp` and missing `ffmpeg` each exiting 3 with the
install line they mean, this platform's ffmpeg advice and a test that it has not
drifted from Tube's table, a local file provably unable to reach the stream path,
`yt_dlp` imported in exactly one place, and a `file:` URL pointed at a real local
track refused with nothing handed to the seam.

Three tests carry `@pytest.mark.integration`, because they ask the machine rather
than a fake: one really plays 0.05 s of a tone on a real output device, and two
really list the devices PortAudio reports. Each **skips out loud** when the
hardware is not there - CI run #3 found a Ubuntu runner with no PortAudio library
and a Windows runner with PortAudio and no devices, which is a fact about the
runner, not about this module.
Not covered: the fetch against a real server (gap 8), true simultaneous-device
behaviour, and the rendered animation (gap 11).

CI run #9 (`2971bf9`) is the first run whose tree carried these cases, and all except the
three `integration` ones are inside the `-m "not integration"` selection it runs, so they
passed on Ubuntu, macOS and Windows at Python 3.12 and 3.13. What that does not say: a
column's `Test suite` step reports an exit code, not a count - the per-column numbers have
never been read, because the log archive needs a signed-in account - and a fake `yt_dlp`
behaves the same on every platform, which is the point of the seam and also its limit.

## Known gaps

1. **The whole file is decoded into memory before playback starts.** `core.load` calls
   `soundfile.read(..., dtype="float32", always_2d=True)`
   (`src/levix/modules/music/core.py:391-399`), so the array handed to PortAudio is
   `frames x channels x 4` bytes at full resolution: a 90-minute 24-bit/96 kHz stereo file is
   about 3.1 GB of RAM on top of the file itself. There is no streaming decode and no
   chunk-and-refill loop, so on an 8 GB machine such a file is refused by the OS, not by a
   LEVIX message. `levix music info FILE` is the safe way to look before playing.
2. **Downsampling aliases.** `core.resample` is `np.interp` per channel
   (`core.py:436-458`) - linear interpolation, exactly as the flag help says - so `--rate`
   from 96 kHz to 44.1 kHz folds the band above 22 kHz down instead of filtering it out. Fine
   for checking a file sounds right, wrong for anything measured. No anti-alias filter is
   applied and none is planned here.
3. **Codecs libsndfile does not carry are refused, not transcoded.** `.m4a .mp4 .aac .wma
   .mka .mkv .ape .mid .midi` are named in `core.MISSING_CODECS` (`core.py:59-69`) and exit 7
   with "re-encode to WAV, FLAC, OGG or MP3", because **the file path never calls ffmpeg**. A
   large part of what people keep on disk is `.m4a`, so this is the module's most visible
   limit. A URL is the deliberate exception: a fetched stream *is* converted to MP3 before
   decoding, which is why a link plays and a local `.m4a` still cannot.
4. **No transport controls.** There is no pause, seek, resume or skip while a file plays;
   the only interaction is Ctrl+C, which closes the stream and exits 130. A long file started
   by accident runs to wherever Ctrl+C lands it, and nothing remembers a position.
5. **The playlist is insertion order, permanently.** `core.list_playlist` ends with
   `ORDER BY id` (`core.py:1034-1040`) and there is no move/reorder/shuffle/repeat command -
   `remove ID` and `add FILE...` are the only edits, so building a running order means
   clearing and re-adding.
6. **No tags at all.** `core.AudioInfo` carries `path, samplerate, channels, frames,
   duration, format, subtype` (`core.py:174-181`) and nothing else, so `info` and `library`
   cannot show title, artist, album, track number or cover art. Reading those needs a tag
   library (mutagen or equivalent) that this module deliberately does not depend on.
7. **One stream at a time, per process.** `core.play_samples` opens a PortAudio stream for
   the call and closes it on every exit path, so two `levix music play` processes compete for
   the device and there is no cross-device simultaneous output. Whether PortAudio's shared
   mode makes that a click, a mix or a refusal is not verified here.
8. **Measured on a synthetic file, not on YouTube.** The fetch is driven through a fake
   `yt_dlp` in the suite, exactly like Tube's, so what is proven is the option set, the
   reported path and the refusal branches. The real behaviour the suite cannot hold - whether
   a given link still serves an audio-only format, whether the extractor survives a YouTube
   change, what a region-blocked or age-gated page answers - is not covered by any test here,
   and **no third-party download was performed for the record**: the build makes no network
   requests. What *was* run for real, on this machine with yt-dlp `2026.10.26` and ffmpeg on
   `PATH`, is `levix music play http://127.0.0.1:1/tone` - the same code path, aimed at a
   closed port on the loopback interface. It took about 3.8 seconds, printed one message
   (`error: yt-dlp could not fetch …` with the tool's own `ERROR: [generic] … Unable to
   download webpage: [WinError 10061]` quoted inside it, because `DownloadError` carries that
   text rather than a second line being printed) and exited **8**. That proves the mapping and
   the single-report rule; it proves nothing about any site.
9. **The stream cache is never pruned.** Replaying a URL costs no network, which is the
   point, but nothing expires `<cache_dir>/streams`: the directory grows by one MP3 per
   distinct URL forever, and `levix music cache` does not exist. Deleting that directory is
   the whole cleanup - including the cleanup gap 10 mentions, because a refused oversize file
   stays exactly where it landed.
10. **A URL is decoded into memory like a file.** Gap 1 applies to a stream too: `core.load`
    reads the whole download before the first sample plays, and the cap that stops the
    *download* is `core.STREAM_MAX_BYTES` = 134,217,728 bytes - it says nothing about the
    decoded array. The arithmetic for a cap-sized download, at 44.1 kHz stereo float32: 128
    kbit/s is 2 h 20 m and about 2.96 GB decoded, 160 kbit/s 1 h 52 m and 2.37 GB, 320 kbit/s
    56 min and 1.18 GB. So the cap is a floor on the damage, not a ceiling on memory. What it
    does protect is the two halves it is checked against: yt-dlp's `max_filesize` when the server declares a length, and the
    file that actually landed - including the cached copy - before `load` touches it, which
    is the step that would cost. What it does not protect: how many cap-sized files
    accumulate (gap 9), the RAM the decode needs (gap 1), or the time yt-dlp spends
    fetching before the check runs. `info` on the cached file is the way to see the length
    first.

11. **The bars have never been seen by a terminal.** `spectrum`, `apply_caps` and `frame_due`
    are pure and asserted; the `Live` renderer is not, because the suite runs with stdout
    captured. So the frame rate, the band count at a real console width and what the
    animation looks like beside a real sound card are described, not verified - and CI never
    runs the one case that could play sound at all, because it is `integration`.

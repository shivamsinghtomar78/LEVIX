# Tube

`levix tube` inspects, downloads and plays online media through **yt-dlp**. It
is a thin, honest surface: Tube implements yt-dlp's own policy and nothing
beyond it - no DRM or download-protection circumvention, no cookie extraction,
no account abuse (`src/levix/modules/tube/core.py` module docstring, enforced by
`test_no_request_ever_asks_for_credentials_or_cookies`).

Requires the `tube` extra (`pip install "levix[tube]"`, yt-dlp >= 2026.10.26).
Without it every command exits **3** with that install line - never an
`ImportError`. `yt_dlp` is imported at exactly one place, `core._make_ydl`, so
`levix tube -h` costs nothing.

## Commands

### `levix tube info URL`

"What a URL is, before spending any bandwidth on it." Metadata only - nothing is
written, nothing is merged.

| Flag | Default | Meaning |
|---|---|---|
| `--formats` | off | Also print the full format table (id, ext, res, fps, vcodec, acodec, bitrate, size, note) |
| `--playlist` | off | Let a playlist URL stay a list |
| `--allow-file-url` | off | Permit a `file://` URL, which yt-dlp disables by default |

Prints a "Tube / media" table: title, id, extractor, url, duration, uploader,
resolution, size range - a field the site does not provide renders as "not
reported", never as 0 or a guess. If the URL lists a playlist it prints "this is
a playlist of N entries - metadata only" and suppresses the format table.
`--formats` is ignored on a playlist listing.

### `levix tube download URL`

Fetch one video (or an opted-in playlist) into a local directory.

| Flag | Default | Meaning |
|---|---|---|
| `-o`, `--output DIR` | empty | Directory to write to; layers `--output` -> `tube.output_dir` -> `~/Downloads`, with the chosen layer printed ("writing to ... (from ...)"). `~` and `%VARS%` expand. |
| `-f`, `--format SPEC` | `tube.default_format` ("best") | `best`, `video`, `audio`, or any explicit yt-dlp selector |
| `--playlist` | off | Opt in to fetching every entry of a playlist URL |
| `--convert-to CODEC` | none | Audio extraction: one of mp3, m4a, opus, vorbis, ogg, wav, aac, flac; anything else is a usage error (exit 2). Implies `--format audio` when no format was given. |
| `--allow-file-url` | off | Same opt-in as `info`; the yt-dlp "file:// URLs are disabled" error is mapped to a message that names this switch |

Behaviour worth knowing:

- **Format aliases.** With ffmpeg: `best`/`video` = `bv*+ba/b`, `audio` = `ba/b`.
  Without ffmpeg they resolve to `ALIASES_SINGLE_FILE` (`b`, `bv/b`, `ba/b`) with
  a printed note - the download genuinely works, it is just not always the
  highest quality, and `video` warns that a single video file may carry no
  audio. An explicit selector is taken literally and never rewritten.
- **The ffmpeg gate.** A request that genuinely needs merging (`+` or a `*`
  selector) or conversion, on a machine without ffmpeg, is refused **before any
  network request** with exit **7** and the platform install command: Windows
  `winget install Gyan.FFmpeg`, macOS `brew install ffmpeg`, otherwise
  `sudo apt install ffmpeg`. LEVIX prints it; it never runs it.
- **Existing files are never re-fetched.** yt-dlp runs with
  `overwrites: False`; when the destination file already exists Tube reports
  "already present, nothing was fetched" and `bytes moved: no - the file was
  already there`. The file on disk keeps its bytes.
- **Playlist warning.** `--playlist` prints: one playlist is many requests -
  the listing plus a request per entry and a download per file; use it only for
  material you are allowed to fetch and expect rate limiting.
- **Output naming**: `%(title)s [%(id)s].%(ext)s` inside the resolved
  directory, which is created if missing (failure to create it exits **5**).
- **Progress**: yt-dlp `progress_hooks` feed one Rich `Live` line (bar,
  downloaded/total bytes, speed, eta). Off a terminal only the final frame is
  printed once, before the summary table.

### `levix tube play URL`

Resolve the stream and hand its URL to a player process. **Nothing is written.**

| Flag | Default | Meaning |
|---|---|---|
| `--player NAME` | empty | Player command to use instead of searching PATH |

Player search order on PATH: `mpv`, `ffplay`, `vlc`, `mplayer`. The request uses
`single_file_plan()` (spec `b`) because a player receives exactly one URL, so
merging is never on the table. No player found -> exit **7** naming every name
tried. No single-file stream URL reported -> exit **8** pointing at
`levix tube download`. A player that exits non-zero -> exit **7** with its own
code. The command line is printed before launch and executed as an argument
list (`shell=False`).

## What it prints

Every dynamic value (site titles, file names, URLs, paths) passes through
`_show()` = Rich markup `escape` plus `terminal.encode_safe`: a video title with
emoji on a cp1252 console comes back with `\uXXXX` escapes instead of crashing,
and `[...]` inside a real filename prints literally so the report matches the
file on disk. Unknown values are reported as "not reported" / "-" rather than
invented.

## What it writes

- Downloaded media into the resolved output directory (never elsewhere).
- One row in the shared command-history table `levix_command_log` (best-effort,
  like every command). Tube owns **no** database tables: its slot in
  `storage.MIGRATIONS` (`"tube": ()`) ships empty and nothing registers into it.

## Safety and policy

- Respect copyright and each site's terms of service; the playlist warning and
  the `--allow-file-url` opt-in exist so mass or disk-reading fetches are
  deliberate, not accidental. `file://` stays disabled by default for the same
  reason yt-dlp disables it: a URL from somewhere else should not read this
  disk.
- No credentials, cookies or DRM handling - tested, not just asserted.
- Ctrl+C during a download or playback is mapped to exit **130**
  (KeyboardInterrupt/SystemExit are BaseExceptions and pass through the
  yt-dlp error mapping untouched).

## Troubleshooting (exit codes)

| Code | Meaning here | Typical fix |
|---|---|---|
| 2 | Bad usage, e.g. an invalid `--convert-to` target | see `levix tube download -h` |
| 3 | yt-dlp not installed | `pip install "levix[tube]"` |
| 5 | Output directory cannot be created | check the path / permissions |
| 7 | ffmpeg needed but absent; no player found; player failed | run the printed install command; install a player (mpv suits a terminal best), or `levix tube download` then play locally |
| 8 | yt-dlp could not handle the URL (network, site change, blocked), or no stream URL | retry, update yt-dlp, or download instead |
| 130 | Interrupted (Ctrl+C) | - |

## Tests

`tests/modules/test_tube.py` - 62 test functions, 76 collected cases on Windows, **no
network**: the single seam
`core._make_ydl` is replaced by a stub recording what the CLI asked for, while
the real command surface above it runs. Covered: alias resolution with and
without ffmpeg, the gate refusing pre-request, per-platform install advice,
player search and argument-list launch, output-directory layering and expansion,
`noplaylist` default and playlist opt-in warning, `overwrites: False`,
`file://` staying disabled and its error hint, option builder (conversion
postprocessor; the forbidden-fields check that no cookies are ever requested),
info dict summarisation with unknown fields, hook math (bytes over percent,
estimates, finished = 100%), cp1252-safe bar, skip-vs-transfer reporting, the
"already present" path, manifest contract, and subprocess tests that help does
not import yt-dlp. Not covered by tests: any real network exchange (impossible
here by design), a real player opening a window, and the fallback in
`tube/cli.py::_configured` that ignores an invalid config value rather than
failing the download.

## Known gaps

1. **No request has ever reached a site from this build.** Every tube test replaces the one
   seam `core._make_ydl` (`src/levix/modules/tube/core.py:251`) with a recorder, so what is
   proven is the dictionary LEVIX hands yt-dlp and the reporting around it - not that a given
   extractor still works, that a rate limit looks like this, or that a real merged file is
   playable. Site failures therefore map to exit **8** with yt-dlp's own words, and those
   words have not been read here. `docs/roadmap/CURRENT_STATUS.md` lists this as the module's
   main verification gap.
2. **The ffmpeg and player verdicts are this machine's, and they are currently both `ok`.**
   `core.ffmpeg_path()` is `shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")`
   (`core.py:109`) and this host now has a winget `yt-dlp.FFmpeg` build providing `ffmpeg`,
   `ffprobe` and `ffplay`, so `capabilities.probe("ffmpeg")` and `probe("media_player")` both
   report `ok`. Consequences: the exit-7 "ffmpeg missing" refusal and its
   `winget install Gyan.FFmpeg` advice are reachable only through a patched probe (which is
   exactly what the tests do), and `levix tube play` would pick `ffplay` - the third
   candidate in `PLAYER_CANDIDATES = ("mpv", "ffplay", "vlc", "mplayer")` (`core.py:34`) -
   because `mpv` is not installed. A real `ffplay` window has never been opened here.
3. **DRM is not detected, only never circumvented.** Nothing in `core.py` reads `has_drm`,
   `format_note` or a licence field; the policy is enforced by what Tube refuses to *pass*
   (`test_no_request_ever_asks_for_credentials_or_cookies`) rather than by what it recognises.
   A protected stream therefore arrives as an ordinary yt-dlp failure at exit **8**, and the
   report cannot say "this is DRM-protected, and LEVIX will not help with that".
4. **No resume, no archive, no throttling, no subtitle or thumbnail options.**
   `build_options` (`core.py:215-245`) sets exactly `format`, `noplaylist`, `quiet`,
   `no_warnings`, `noprogress`, `ignoreerrors`, `overwrites`, `progress_hooks`, `paths`,
   `outtmpl`, the `FFmpegExtractAudio` postprocessor and `enable_file_urls` - nothing else.
   yt-dlp's own `--download-archive`, `--limit-rate`, `--concurrent-fragments` and
   `--write-subs` are unreachable through this surface, and whatever yt-dlp does with a
   leftover `.part` file is its own default rather than a choice LEVIX exposes or has
   tested. A re-run of a playlist re-extracts every listing either way, because
   `overwrites: False` only protects bytes already on disk.
5. **`tube info` on a playlist is metadata for the list only.** It prints "this is a playlist
   of N entries - metadata only", suppresses the format table and does not enumerate the
   entries; there is no `--playlist-items`-style preview, so N unknown-size items become N
   downloads the moment `--playlist` is used.
6. **A bad config value is silently replaced by the packaged default.** `_configured`
   (`src/levix/modules/tube/cli.py:346-356`) catches `ConfigError`, `TypeError` and
   `ValueError` and returns the fallback, on the reasoning that a broken `tube.output_dir`
   should not stop a download. The root callback validates `config.toml` before any command
   runs, so in normal use this branch is not reachable - but it is untested, and it means a
   hand-edited bad value shows up as "it wrote to ~/Downloads" rather than as an error.

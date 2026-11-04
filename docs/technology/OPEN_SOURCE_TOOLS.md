# Open-Source Tools LEVIX Relies On At Runtime

LEVIX is a Python program, but some capabilities live outside the process: an
ffmpeg binary on PATH, a media player, a running Ollama server. This document
records how each is detected, what happens when it is absent, and the single rule
that governs all of them.

## The rule

**LEVIX never installs, upgrades or modifies anything system-wide.** Every gate
that finds a missing tool prints the command that would fix it and exits; none of
them runs it. `levix update` is the same story for LEVIX itself: it queries PyPI
and reports, and its help text is literally `--check/--install-nothing` ("Always
checks; LEVIX never self-updates" - `src/levix/commands/update_cmd.py`). The one
external program LEVIX ever executes that touches anything outside its own files
is Windows `icacls`, and only to set an owner-only ACL on LEVIX's *own* secrets
file (`src/levix/secrets.py::_harden`). Every subprocess uses an argument list
with `shell=False`; no command string is ever re-parsed.

## ffmpeg

- **Used for**: merging separate video+audio streams and audio conversion in
  `levix tube`. Never used by `levix music` - libsndfile decodes in-process.
- **Detection**: `shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")`
  (`tube/core.py::ffmpeg_path`). The capabilities probe (`capabilities.py`)
  reports OK with the resolved path, or MISSING with "not on PATH".
- **When missing**:
  - `levix tube info` still works; it prints the note "ffmpeg is not installed,
    so merging separate video and audio streams and audio conversion are both
    unavailable here" plus the platform install command, and single-file format
    aliases silently degrade: `best`/`video`/`audio` resolve to the
    `ALIASES_SINGLE_FILE` selectors (`b`, `bv/b`, `ba/b`) with an explicit note.
  - `levix tube download --format bv*+ba/b` (or any merging selector), or any
    `--convert-to`, hits the gate `core.ensure_ffmpeg` **before any request is
    made** and exits **7** (`ExternalToolError`) with the message "this request
    needs ffmpeg to ... and ffmpeg is not installed" and the fix command.
- **Per-platform install advice** (`tube/core.py::FFMPEG_INSTALL_COMMANDS`):
  - Windows (`win32`, and `cygwin`): `winget install Gyan.FFmpeg`
  - macOS (`darwin`): `brew install ffmpeg`
  - Everything else (fallback): `sudo apt install ffmpeg`
- **Exit code when ffmpeg itself fails mid-download**: yt-dlp surfaces that as
  its own exception; Tube maps it to exit **8** (`ProviderError`, "yt-dlp could
  not handle <url>").

## Media players: mpv, ffplay, vlc, mplayer

- **Used for**: `levix tube play` resolves one stream URL and hands it to a
  player process. Nothing is written to disk by `play`.
- **Detection**: `core.find_player` walks PATH via `shutil.which` over
  `PLAYER_CANDIDATES = ("mpv", "ffplay", "vlc", "mplayer")`, or the single name
  given with `--player`. It never guesses a location it did not find.
- **When missing**: exit **7** (`ExternalToolError`) with "no media player found
  on PATH: looked for mpv, ffplay, vlc, mplayer" and the suggestion to
  `levix tube download <url>` instead.
- **When the player exits non-zero**: exit **7**, "<player> exited with code N".
  The player's own stdout/stderr pass through; LEVIX returns its exit code.
- Noted inconsistency: the `media_player` capabilities probe tries
  `("mpv", "vlc", "ffplay", "mplayer")` - a different order from Tube's own
  search - so `levix doctor` and `levix tube play` can prefer different players
  when two are installed.

## PortAudio

- **Used for**: all audio output in `levix music`.
- **Delivery**: **bundled inside the `sounddevice` wheel** (0.5.6 installed). It
  is not a system tool, LEVIX never installs it, and `pip install "levix[music]"`
  is the only acquisition path. Detection is therefore `importlib.util.find_spec`
  - the `audio_output` capabilities probe reports MISSING with
  `pip install "levix[music]"` as the hint when sounddevice/soundfile are absent.
- **When no device exists**: `levix music devices` lists whatever PortAudio
  reports and prints the honest note "no device with output channels: playback
  cannot start on this machine", or "PortAudio reports no default output device;
  pass --device N from the list". Exit stays **0** - listing worked.
- **When opening a stream fails**: `core.play_samples` wraps any PortAudio
  refusal into `AudioDeviceError` -> exit **7**, "PortAudio could not play on
  <device>: ..." with the hint to run `levix music devices`.

## libsndfile

- **Used for**: decoding WAV, FLAC, OGG, MP3 and friends in `levix music`.
- **Delivery**: **bundled inside the `soundfile` wheel** (0.14.0 installed); the
  decoder actually in use is reported by `levix music info` via
  `core.decoder_version()` ("soundfile <ver> / libsndfile <ver>").
- **When a codec is missing** (e.g. `.m4a`, `.mp4`, `.aac`, `.wma`, `.mkv`,
  `.ape`, `.mid`): exit **7** (`UnsupportedFormatError`) naming the codec, with
  the message stating explicitly that "LEVIX never calls ffmpeg, so there is no
  fallback to enable". A codec it does not carry is reported as missing, never
  faked.

## Ollama (local AI server)

- **Used for**: the `ollama` provider of `levix ai`
  (`POST {ollama_url}/api/chat`, `GET {ollama_url}/api/tags`), default URL
  `http://127.0.0.1:11434` (config key `ai.ollama_url`).
- **Detection**: LEVIX does not probe for an `ollama` binary; it talks HTTP to
  the configured URL through one `httpx.Client`. `levix ai models` and
  `levix ai check --live` are the reachability tests the CLI offers (subcommands:
  ask, explain, command, models, check).
- **When not running**: exit **8** (`ProviderError`) - "cannot reach ollama at
  <url>: ConnectError" with hint "start the server or point --base-url /
  --ollama-url at the right host"; a timeout gives "ollama did not answer <url>
  within Ns". Nothing is installed or started for you.

## PyPI (self-update check only)

`levix update` GETs `https://pypi.org/pypi/levix/json` with stdlib
`urllib.request`, a 6 s default timeout (`--timeout`, 1.0-60.0). No response
gives exit **8** with "this is a network limitation, not an indication that you
are up to date."

## yt-dlp and other in-process libraries

yt-dlp (2026.10.26), rich, textual, typer, tomlkit, platformdirs, keyring,
httpx, numpy and psutil are Python dependencies, not external tools: they run in
-process, are version-pinned in `pyproject.toml`, and their absence is a missing
**extra**, reported with exit **3** and the exact `pip install "levix[...]"`
line - never an `ImportError`. See `docs/technology/DEPENDENCIES.md`.

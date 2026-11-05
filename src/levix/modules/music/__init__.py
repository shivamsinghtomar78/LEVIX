"""LEVIX Music - native playback through libsndfile and PortAudio, no ffmpeg for a file.

`levix --help` imports this file once per registered module, so it stays pure data: no
`soundfile`, no `sounddevice`, no numpy, no Typer. Decoding and the audio callback live
in `core.py`, rendering in `cli.py`, and both are unreachable until a `levix music`
command actually runs.

Design note: `soundfile` bundles libsndfile and `sounddevice` bundles PortAudio, so
decoding and output are in-process native libraries and nothing here shells out for a file
on disk. One source is the exception: an `http(s)` link is fetched by yt-dlp, and the
conversion that makes it decodable runs inside yt-dlp's own postprocessor - LEVIX builds no
command line, for ffmpeg or for anything else (`core.fetch_audio`).
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, PackageRef, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="music",
    title="Music",
    summary="Play, inspect and queue audio natively, from a file or one fetched link.",
    cli_path="levix.modules.music.cli:build_app",
    commands=(
        CommandInfo("play", "Decode one file or one link and play it on an output device."),
        CommandInfo("info", "Sample rate, channels, duration, format and codec verdict."),
        CommandInfo("devices", "Every audio device PortAudio can see, with defaults."),
        CommandInfo("library", "Scan music.library_dir (or --root) for playable files."),
        CommandInfo("playlist", "list, add, remove, clear and play a stored queue."),
    ),
    requirements=(
        PackageRef("soundfile", "soundfile", minimum="0.14"),
        PackageRef("sounddevice", "sounddevice", minimum="0.5"),
    ),
    extras=("music",),
    capabilities=("libsndfile", "portaudio"),
    # NETWORK and FS_WRITE belong to one command, `play URL`: the fetch and the cache copy
    # it leaves behind. A file on disk needs neither, and `info`, `devices`, `library` and
    # `playlist` touch neither. Permissions are a disclosure, not a wall - see
    # docs/security/PERMISSIONS.md.
    permissions=frozenset(
        {Permission.AUDIO, Permission.FS_READ, Permission.FS_WRITE, Permission.NETWORK}
    ),
    # One TTY cannot host two Textual apps, and audio wants the real device, so the
    # dashboard suspends instead of embedding a screen. The entry point it offers is the
    # read-only library scan - nothing that can leave a stream open.
    ui=UiSpec(mode="suspend", argv=("music", "library")),
    documentation="docs/modules/MUSIC.md",
)

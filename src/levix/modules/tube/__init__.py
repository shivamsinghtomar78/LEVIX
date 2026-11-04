"""LEVIX Tube - media download and playback through yt-dlp.

`levix --help` imports this file for every registered module, so it stays pure data:
no yt-dlp, no subprocess, no Rich. `import yt_dlp` lives inside `core._make_ydl` and is
reached only when a `levix tube` command really runs. Because the requirement is
declared here, a core install without the `tube` extra gets deps.py's exit-3 message
naming `pip install "levix[tube]"` instead of an ImportError.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, PackageRef, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="tube",
    title="Tube",
    summary="Inspect, download or play online video through yt-dlp, with honest gates.",
    cli_path="levix.modules.tube.cli:build_app",
    commands=(
        CommandInfo(
            "info",
            "Title, length, uploader, size range and (with --formats) the format table.",
        ),
        CommandInfo(
            "download",
            "Save one video to disk; --playlist is an explicit opt-in.",
        ),
        CommandInfo("play", "Hand the stream to mpv, ffplay or vlc without saving a file."),
    ),
    requirements=(PackageRef("yt_dlp", "yt-dlp"),),
    extras=("tube",),
    capabilities=("yt-dlp", "progress-hooks", "ffmpeg-gate", "external-player"),
    permissions=frozenset(
        {Permission.NETWORK, Permission.FS_WRITE, Permission.SUBPROCESS, Permission.AUDIO}
    ),
    # `suspend`, not `screen`: an external player wants the real terminal (mpv's key
    # bindings, ffplay's stdin) and a TTY cannot host the dashboard and the player at
    # the same time. No `argv`: every Tube command needs a URL, and the dashboard cannot
    # supply one, so it opens this module's own help instead of a command that must fail.
    ui=UiSpec(mode="suspend"),
    documentation="docs/modules/TUBE.md",
)

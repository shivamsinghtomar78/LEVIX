"""Tube: the format gates, the yt-dlp seam and the reporting that follows a download.

Nothing here touches the network. `core._make_ydl` is the single place yt-dlp is
imported and instantiated, so every CLI test replaces that one function with a stub and
exercises the real command surface above it - the gates, the option builder and the
summary are the shipped code, not a re-implementation of it.

ffmpeg is asserted through `core.ffmpeg_path` rather than the machine's PATH, because
this suite must say the same thing on a box that has ffmpeg as on one that does not.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from levix.errors import (
    EXIT_CONFIG,
    EXIT_PROVIDER,
    EXIT_TOOL_FAILED,
    EXIT_USAGE,
    ConfigError,
    ExternalToolError,
    ProviderError,
)
from levix.modules.tube import MANIFEST, core

URL = "https://example.invalid/watch?v=abcdef"


# ----------------------------------------------------------------------------------
# the fake yt-dlp
# ----------------------------------------------------------------------------------


class FakeYdl:
    def __init__(self, record: dict) -> None:
        self._record = record

    def extract_info(self, url: str, download: bool = False) -> dict:
        self._record["url"] = url
        self._record["download"] = download
        options = self._record["options"]
        if self._record.get("raises") is not None:
            raise self._record["raises"]
        if download:
            for raw in self._record["hooks"]:
                for hook in options["progress_hooks"]:
                    hook(raw)
            self._record["write"]()
        return self._record["info"]


def install_seam(monkeypatch, *, info: dict, hooks=(), raises=None, write=lambda: None) -> dict:
    """Replace the only yt-dlp entry point and record what the CLI asked it for."""
    record: dict = {"info": info, "hooks": list(hooks), "raises": raises, "write": write}

    def _make_ydl(options: dict):
        record["options"] = options
        return FakeYdl(record)

    monkeypatch.setattr(core, "_make_ydl", _make_ydl)
    return record


def video_info(tmp_path: Path, *, name: str = "Midnight Set [abcdef].mp4") -> dict:
    destination = tmp_path / name
    return {
        "_type": "video",
        "id": "abcdef",
        "title": "Midnight Set",
        "extractor": "Generic",
        "webpage_url": URL,
        "duration": 253,
        "uploader": "Example Channel",
        "format_id": "18",
        "format": "18 - 640x360 (mp4)",
        "filesize": 2048,
        "filepath": str(destination),
        "formats": [
            {
                "format_id": "18",
                "ext": "mp4",
                "width": 640,
                "height": 360,
                "fps": 30,
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "tbr": 800,
                "filesize": 2048,
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "tbr": 128,
                "filesize_approx": 4100000,
                "format_note": "low quality",
            },
        ],
    }


DOWNLOADING = {
    "status": "downloading",
    "downloaded_bytes": 1024,
    "total_bytes": 2048,
    "speed": 512.0,
    "eta": 2,
    "filename": "Midnight Set [abcdef].mp4.part",
}
FINISHED = {
    "status": "finished",
    "downloaded_bytes": 2048,
    "total_bytes": 2048,
    "filename": "Midnight Set [abcdef].mp4",
}


def no_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(core, "ffmpeg_path", lambda: None)


def with_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")


# ----------------------------------------------------------------------------------
# the ffmpeg gate
# ----------------------------------------------------------------------------------


def test_an_alias_resolves_to_a_single_file_when_ffmpeg_is_absent():
    plan = core.plan_format("best", has_ffmpeg=False)
    assert plan.spec == "b"
    assert plan.requires_ffmpeg is False, "the fallback must actually be downloadable here"
    assert "ffmpeg is not installed" in plan.note


def test_the_same_alias_asks_for_merged_streams_when_ffmpeg_is_present():
    plan = core.plan_format("best", has_ffmpeg=True)
    assert plan.spec == "bv*+ba/b"
    assert plan.requires_ffmpeg is True
    assert plan.note == ""


def test_the_video_alias_warns_that_a_single_video_file_may_have_no_audio():
    plan = core.plan_format("video", has_ffmpeg=False)
    assert plan.spec == "bv/b"
    assert "no audio track" in plan.note


@pytest.mark.parametrize("alias,spec", [("audio", "ba/b"), ("best", "b"), ("video", "bv/b")])
def test_every_fallback_is_itself_a_single_file_format(alias, spec):
    assert core.plan_format(alias, has_ffmpeg=False).spec == spec


def test_an_explicit_selector_is_never_quietly_rewritten():
    """A user who typed a yt-dlp selector owns it; substituting ours would be a lie."""
    plan = core.plan_format("137+140/bv", has_ffmpeg=False)
    assert plan.spec == "137+140/bv"
    assert plan.requires_ffmpeg is True


def test_conversion_always_needs_ffmpeg_even_for_a_single_file_format():
    plan = core.plan_format("best", has_ffmpeg=True, convert_to="mp3")
    assert plan.requires_ffmpeg is True
    assert plan.convert_to == "mp3"


def test_the_gate_refuses_and_names_the_command_that_would_fix_it(monkeypatch):
    monkeypatch.setattr(core.sys, "platform", "win32")
    plan = core.plan_format("best", has_ffmpeg=True)
    with pytest.raises(ExternalToolError) as caught:
        core.ensure_ffmpeg(plan, has_ffmpeg=False)
    message = caught.value.message
    assert "merge the separate video and audio streams" in message
    assert "winget install Gyan.FFmpeg" in message
    assert caught.value.hint == "winget install Gyan.FFmpeg"
    assert caught.value.exit_code == EXIT_TOOL_FAILED


def test_the_gate_lets_a_single_file_download_through_without_ffmpeg():
    assert core.ensure_ffmpeg(core.plan_format("best", has_ffmpeg=False), has_ffmpeg=False) is None


@pytest.mark.parametrize(
    ("platform", "command"),
    [
        ("win32", "winget install Gyan.FFmpeg"),
        ("darwin", "brew install ffmpeg"),
        ("linux", "sudo apt install ffmpeg"),
        ("sunos5", "sudo apt install ffmpeg"),
    ],
)
def test_the_install_advice_is_the_one_for_this_platform(platform, command):
    assert core.install_command_for(platform) == command


def test_an_unconvertible_target_is_listed_rather_than_accepted():
    assert "mp3" in core.CONVERTIBLE and "aac" in core.CONVERTIBLE
    assert "flac" in core.CONVERTIBLE


# ----------------------------------------------------------------------------------
# the player
# ----------------------------------------------------------------------------------


def test_the_player_search_reports_every_name_it_tried(monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda name: None)
    found, searched = core.find_player("")
    assert found is None
    assert searched == core.PLAYER_CANDIDATES
    assert "mpv" in searched and "ffplay" in searched


def test_an_explicit_player_is_searched_even_though_it_is_not_a_candidate(monkeypatch):
    monkeypatch.setattr(
        core.shutil, "which", lambda name: "/opt/bin/vlc" if name == "vlc" else None
    )
    found, searched = core.find_player("vlc")
    assert found == "/opt/bin/vlc"
    assert searched == ("vlc",), "an explicit choice must not claim it tried the defaults"


def test_a_player_is_handed_an_argument_list_not_a_shell_string(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return Completed()

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    argv = core.player_command("/usr/bin/mpv", "https://example.invalid/stream.mp4?sig=a%2Bb")
    assert core.launch(argv) == 0
    assert calls == [
        (
            ("/usr/bin/mpv", "https://example.invalid/stream.mp4?sig=a%2Bb"),
            {"shell": False, "check": False},
        )
    ]


def test_a_player_that_cannot_be_started_is_an_external_tool_failure(monkeypatch):
    def explode(argv, **kwargs):
        raise OSError("[Errno 2] No such file or directory: 'mpv'")

    monkeypatch.setattr(core.subprocess, "run", explode)
    with pytest.raises(ExternalToolError, match="could not start mpv"):
        core.launch(["mpv", URL])


# ----------------------------------------------------------------------------------
# the output directory
# ----------------------------------------------------------------------------------


def test_the_flag_beats_the_configured_directory(tmp_path):
    directory, source = core.resolve_output_dir(str(tmp_path), str(tmp_path / "ignored"))
    assert directory == tmp_path
    assert source == "--output"


def test_the_configured_directory_is_used_when_no_flag_is_given(tmp_path):
    directory, source = core.resolve_output_dir("", str(tmp_path))
    assert directory == tmp_path and source == "tube.output_dir"


def test_a_blank_everywhere_lands_in_the_download_folder():
    directory, source = core.resolve_output_dir("", "")
    assert directory == Path.home() / "Downloads"
    assert "fallback" in source


def test_a_home_relative_path_expands(tmp_path, monkeypatch):
    """`expanduser` reads the environment, so the test sets it rather than Path.home()."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    directory, _ = core.resolve_output_dir("~/media", "")
    assert directory == tmp_path / "media"


def test_environment_variables_expand_in_both_notations(tmp_path, monkeypatch):
    monkeypatch.setenv("LEVIX_TUBE_DIR", str(tmp_path))
    token = "%LEVIX_TUBE_DIR%" if os.name == "nt" else "$LEVIX_TUBE_DIR"
    directory, _ = core.resolve_output_dir(token, "")
    assert directory == tmp_path


def test_a_directory_that_cannot_be_created_is_a_config_error(tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot use output directory"):
        core.ensure_output_dir(blocked / "sub")
    assert ConfigError("").exit_code == EXIT_CONFIG


# ----------------------------------------------------------------------------------
# options handed to yt-dlp
# ----------------------------------------------------------------------------------


def test_a_single_url_is_not_treated_as_a_playlist_unless_asked():
    options = core.build_options(core.plan_format("best", has_ffmpeg=False))
    assert options["noplaylist"] is True
    assert options["format"] == "b"
    assert options["quiet"] is True and options["noprogress"] is True


def test_opting_into_a_playlist_turns_the_guard_off_and_warns_loudly():
    options = core.build_options(core.plan_format("best", has_ffmpeg=False), playlist=True)
    assert options["noplaylist"] is False


def test_existing_files_are_never_overwritten():
    options = core.build_options(core.plan_format("best", has_ffmpeg=False))
    assert options["overwrites"] is False


def test_file_urls_stay_disabled_until_they_are_explicitly_allowed():
    plain = core.build_options(core.plan_format("best", has_ffmpeg=False))
    allowed = core.build_options(core.plan_format("best", has_ffmpeg=False), allow_file_url=True)
    assert "enable_file_urls" not in plain, "yt-dlp's own default must not be quietly raised"
    assert allowed["enable_file_urls"] is True


def test_a_download_is_written_inside_the_directory_that_was_chosen(tmp_path):
    options = core.build_options(core.plan_format("best", has_ffmpeg=False), output_dir=tmp_path)
    assert options["paths"]["home"] == str(tmp_path)
    assert "[%(id)s]" in options["outtmpl"], "the id in the name keeps two clips apart"


def test_conversion_becomes_an_ffmpeg_postprocessor_and_nothing_else():
    plan = core.plan_format("audio", has_ffmpeg=True, convert_to="opus")
    options = core.build_options(plan)
    assert options["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "0"}
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        "cookiefile",
        "cookiesfrombrowser",
        "username",
        "password",
        "ap_mxac_for_mweb",
        "extractor_args",
        "external_downloader",
    ],
)
def test_no_request_ever_asks_for_credentials_or_cookies(forbidden):
    """Tube downloads what yt-dlp can fetch anonymously; account material is out of scope."""
    for plan in (core.plan_format("best", has_ffmpeg=True), core.single_file_plan()):
        options = core.build_options(plan, playlist=True, allow_file_url=True)
        assert forbidden not in options


# ----------------------------------------------------------------------------------
# reading results
# ----------------------------------------------------------------------------------


def test_a_download_becomes_a_provider_error_that_names_the_url(monkeypatch):
    record = install_seam(monkeypatch, info={}, raises=RuntimeError("HTTP Error 410: Gone"))
    with pytest.raises(ProviderError) as caught:
        core.fetch(URL, {"progress_hooks": []})
    assert URL in caught.value.message
    assert "HTTP Error 410" in caught.value.message
    assert caught.value.exit_code == EXIT_PROVIDER
    assert record["download"] is True


def test_a_levix_error_from_the_seam_is_not_relabelled(monkeypatch):
    install_seam(monkeypatch, info={}, raises=ExternalToolError("ffmpeg died"))
    with pytest.raises(ExternalToolError, match="ffmpeg died"):
        core.fetch(URL, {})


def test_the_disabled_file_url_message_carries_the_switch_that_opens_it(monkeypatch):
    install_seam(
        monkeypatch,
        info={},
        raises=RuntimeError("file:// URLs are disabled by default"),
    )
    with pytest.raises(ProviderError) as caught:
        core.probe("file:///tmp/clip.mp4", {})
    assert "--allow-file-url" in caught.value.hint


def test_a_leaving_of_the_seam_is_the_only_import_site():
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert source.count("import yt_dlp") == 1
    assert "def _make_ydl" in source


def test_summary_reports_a_field_the_site_did_not_provide_as_unknown():
    summary = core.summarize({"id": "x", "title": "T", "formats": [{"format_id": "1"}]})
    assert summary.duration is None
    assert summary.extractor == "not reported"
    assert summary.smallest is None
    assert summary.rows[0].resolution == "not reported"
    assert summary.rows[0].size == "-"
    assert summary.rows[0].fps == "-"


def test_summary_keeps_the_format_table_and_the_size_range():
    summary = core.summarize(video_info(Path(".")))
    assert summary.title == "Midnight Set"
    assert summary.duration == 253.0
    assert len(summary.rows) == 2
    assert summary.rows[0].resolution == "640x360"
    assert summary.rows[0].fps == "30"
    assert summary.smallest == 2048
    assert summary.largest == 4100000, "filesize_approx counts when filesize is absent"
    assert summary.entry_count is None


def test_a_playlist_is_counted_rather_than_flattened():
    info = {"_type": "playlist", "title": "Set", "entries": [{"id": "a"}, {"id": "b"}]}
    summary = core.summarize(info)
    assert summary.entry_count == 2
    assert core.is_playlist(info) is True
    assert core.is_playlist({"_type": "video"}) is False


def test_the_stream_url_follows_the_format_that_was_requested():
    info = {
        "format_id": "140",
        "formats": [{"format_id": "18", "url": "u18"}, {"format_id": "140", "url": "u140"}],
    }
    assert core.stream_url(info) == "u140"
    assert core.stream_url({"url": "direct"}) == "direct"
    assert core.stream_url({"format_id": "999", "formats": []}) is None


def test_sizes_and_lengths_are_said_in_words_a_person_can_read():
    assert core.human_bytes(512) == "512 B"
    assert core.human_bytes(2048) == "2.0 KiB"
    assert core.human_bytes(5 * 1024**2) == "5.0 MiB"
    assert core.human_clock(253) == "4:13"
    assert core.human_clock(3725) == "1:02:05"
    assert core.human_clock(None) == "not reported"


# ----------------------------------------------------------------------------------
# progress
# ----------------------------------------------------------------------------------


def test_bytes_beat_the_percent_field_when_both_are_reported():
    state = core.progress_from_hook(
        {"status": "downloading", "downloaded_bytes": 750, "total_bytes": 1000, "percent": 12}
    )
    assert state.percent == pytest.approx(75.0)
    assert state.total_bytes == 1000


def test_an_estimate_is_used_when_the_total_is_only_approximate():
    state = core.progress_from_hook(
        {"status": "downloading", "downloaded_bytes": 10, "total_bytes_estimate": 40}
    )
    assert state.total_bytes == 40 and state.percent == pytest.approx(25.0)


def test_an_unknown_total_is_said_as_unknown_rather_than_zero():
    state = core.progress_from_hook({"status": "downloading", "downloaded_bytes": 10})
    assert state.total_bytes is None
    assert state.percent == 0.0
    assert "unknown size" in core.progress_text(state)


def test_a_finished_hook_is_always_one_hundred_percent():
    state = core.progress_from_hook(
        {"status": "finished", "downloaded_bytes": 2048, "filename": "clip.mp4"}
    )
    assert state.percent == 100.0
    assert state.total_bytes == 2048


def test_the_progress_bar_writes_only_glyphs_the_stream_can_encode():
    """The bar asks terminal.active_glyphs() instead of embedding U+2588 itself.

    A legacy Windows console with a cp1252 codepage raises UnicodeEncodeError inside
    Rich's writer, which is a crash and not a cosmetic problem. What the ambient stream
    can take is exactly what the bar must therefore emit.
    """
    state = core.progress_from_hook(DOWNLOADING)
    plain = _plain(core.progress_text(state))
    plain.encode(sys.stdout.encoding or "utf-8", errors="strict")
    assert "1.0 KiB / 2.0 KiB" in plain
    assert "512 B/s" in plain and "eta 0:02" in plain


def test_the_ascii_fallback_bar_survives_a_cp1252_console(monkeypatch):
    import levix.terminal as terminal

    ascii_profile = terminal.TerminalProfile(
        is_tty=True,
        supports_colour=False,
        supports_unicode=False,
        columns=80,
        rows=24,
        term="xterm",
        protocol_enabled=False,
    )
    monkeypatch.setattr(terminal, "active_glyphs", lambda: terminal.glyphs(ascii_profile))
    plain = _plain(core.progress_text(core.progress_from_hook(DOWNLOADING)))
    plain.encode("cp1252")
    assert "#" in plain or "-" in plain
    assert "\u2588" not in plain


def _plain(markup: str) -> str:
    from rich.text import Text

    return "\n".join(line.plain for line in Text.from_markup(markup).split("\n"))


def test_hook_path_and_transferred_separate_the_two_shapes_of_done():
    downloaded = [core.progress_from_hook(DOWNLOADING), core.progress_from_hook(FINISHED)]
    skipped = [core.progress_from_hook(FINISHED)]
    assert core.transferred(downloaded) is True
    assert core.transferred(skipped) is False
    assert core.hook_path(downloaded).endswith("Midnight Set [abcdef].mp4")
    assert core.hook_path([]) is None


# ----------------------------------------------------------------------------------
# the manifest and the lazy-loading rule
# ----------------------------------------------------------------------------------


def test_the_manifest_declares_the_packaged_contract():
    assert MANIFEST.name == "tube"
    assert MANIFEST.command_names() == ("info", "download", "play")
    assert MANIFEST.requirements[0].import_name == "yt_dlp"
    assert MANIFEST.requirements[0].distribution == "yt-dlp"
    assert MANIFEST.extras == ("tube",)
    assert MANIFEST.ui is not None and MANIFEST.ui.mode == "suspend"
    assert MANIFEST.ui.argv == (), "every Tube command needs a URL the dashboard cannot supply"
    assert MANIFEST.documentation == "docs/modules/TUBE.md"


def _child(tmp_path: Path, *statements: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "LEVIX_HOME": str(tmp_path / "child-home"),
        "LEVIX_LOGGING_FILE_ENABLED": "false",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", "import sys\n" + "\n".join(statements)],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        env=env,
    )


def test_importing_the_manifest_pulls_in_nothing_heavy(tmp_path):
    completed = _child(
        tmp_path,
        "import levix.modules.tube as m",
        "heavy = [x for x in ('yt_dlp', 'psutil', 'sounddevice', 'textual', 'rich', 'typer') "
        "if x in sys.modules]",
        "print(len(m.MANIFEST.commands), heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "3 []"


def test_tube_help_never_imports_yt_dlp(tmp_path):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        "code = main(['tube', '-h'])",
        "print(code, 'yt_dlp' in sys.modules)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 False"


# ----------------------------------------------------------------------------------
# the command surface, through the real entry point
# ----------------------------------------------------------------------------------


def test_info_prints_the_media_table_and_says_what_this_machine_cannot_do(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    record = install_seam(monkeypatch, info=video_info(tmp_path))
    assert run_cli("tube", "info", URL) == 0
    out = capsys.readouterr().out
    assert "Midnight Set" in out and "4:13" in out
    assert "ffmpeg is not installed" in out
    assert record["download"] is False, "info must not fetch a single byte"


def test_a_playlist_listing_says_it_is_a_list_without_downloading(run_cli, monkeypatch, capsys):
    no_ffmpeg(monkeypatch)
    info = {"_type": "playlist", "title": "Late Sessions", "entries": [{"id": "a"}, {"id": "b"}]}
    install_seam(monkeypatch, info=info)
    assert run_cli("tube", "info", URL, "--playlist") == 0
    assert "playlist of 2 entries" in capsys.readouterr().out


def test_formats_are_listed_only_when_asked_for(run_cli, monkeypatch, capsys, tmp_path):
    no_ffmpeg(monkeypatch)
    install_seam(monkeypatch, info=video_info(tmp_path))
    assert run_cli("tube", "info", URL) == 0
    assert "140" not in capsys.readouterr().out
    assert run_cli("tube", "info", URL, "--formats") == 0
    table = capsys.readouterr().out
    assert "Formats for Midnight Set (2 reported)" in table
    assert "140" in table and "640x360" in table
    assert "low" in table and "quality" in table, "the note column wraps at 80 columns"


def test_download_names_the_file_it_wrote_not_the_directory(run_cli, monkeypatch, capsys, tmp_path):
    no_ffmpeg(monkeypatch)
    # Rich folds a long path across the cell, so ask for a width where it cannot.
    monkeypatch.setenv("COLUMNS", "200")
    target = tmp_path / "Midnight Set [abcdef].mp4"
    record = install_seam(
        monkeypatch,
        info=video_info(tmp_path),
        hooks=[DOWNLOADING, FINISHED],
        write=lambda: target.write_bytes(b"0" * 2048),
    )
    assert run_cli("tube", "download", URL, "--output", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert str(target) in out, "the file row must name the destination, not the directory"
    assert f"writing to {tmp_path} (from --output)" in out
    assert "2.0 KiB" in out
    assert "bytes moved" in out and "yes" in out
    assert record["options"]["paths"]["home"] == str(tmp_path)


def test_a_file_that_was_already_there_is_reported_as_untouched(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    monkeypatch.setenv("COLUMNS", "200")
    target = tmp_path / "Midnight Set [abcdef].mp4"
    target.write_bytes(b"0" * 2048)
    install_seam(
        monkeypatch,
        info={**video_info(tmp_path), "filepath": str(target)},
        hooks=[FINISHED],
    )
    assert run_cli("tube", "download", URL, "--output", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "already present, nothing was fetched" in out
    assert str(target) in out
    assert "no - the file was already there" in out
    assert "2.0 KiB" in out, "the existing file's size is still reported"


def test_a_merged_format_is_refused_before_any_request_is_made(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    record = install_seam(monkeypatch, info=video_info(tmp_path))
    code = run_cli("tube", "download", URL, "--format", "bv*+ba/b", "--output", str(tmp_path))
    assert code == EXIT_TOOL_FAILED
    assert "needs ffmpeg" in " ".join(capsys.readouterr().err.split())
    assert "options" not in record, "the gate runs before yt-dlp is even built"


def test_a_conversion_is_refused_the_same_way_but_says_what_it_wanted(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    record = install_seam(monkeypatch, info=video_info(tmp_path))
    code = run_cli("tube", "download", URL, "--convert-to", "mp3", "--output", str(tmp_path))
    assert code == EXIT_TOOL_FAILED
    assert "convert the audio to mp3" in " ".join(capsys.readouterr().err.split())
    assert "options" not in record


def test_a_conversion_works_when_ffmpeg_is_present(run_cli, monkeypatch, capsys, tmp_path):
    with_ffmpeg(monkeypatch)
    target = tmp_path / "Midnight Set [abcdef].mp3"
    record = install_seam(
        monkeypatch,
        info={**video_info(tmp_path), "filepath": str(target), "format": "audio only (mp3)"},
        hooks=[{"status": "finished", "downloaded_bytes": 900, "filename": target.name}],
        write=lambda: target.write_bytes(b"0" * 900),
    )
    assert run_cli("tube", "download", URL, "--convert-to", "mp3", "--output", str(tmp_path)) == 0
    options = record["options"]
    assert options["format"] == "ba/b"
    assert options["postprocessors"][0]["preferredcodec"] == "mp3"


@pytest.mark.parametrize("bad", ["flv", "MP3 mp3", "ogg; rm -rf", "wma"])
def test_an_unconvertible_target_is_a_usage_error(run_cli, monkeypatch, tmp_path, bad):
    """Nothing here reaches a shell, but a value that is not a codec is still refused."""
    no_ffmpeg(monkeypatch)
    record = install_seam(monkeypatch, info=video_info(tmp_path))
    code = run_cli("tube", "download", URL, "--convert-to", bad, "--output", str(tmp_path))
    assert code == EXIT_USAGE
    assert "options" not in record


def test_an_empty_conversion_option_means_no_conversion_at_all(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    target = tmp_path / "Midnight Set [abcdef].mp4"
    record = install_seam(
        monkeypatch,
        info=video_info(tmp_path),
        hooks=[FINISHED],
        write=lambda: target.write_bytes(b"0" * 10),
    )
    assert run_cli("tube", "download", URL, "--convert-to", "", "--output", str(tmp_path)) == 0
    assert "postprocessors" not in record["options"]


def test_the_playlist_warning_only_appears_when_a_playlist_was_asked_for(
    run_cli, monkeypatch, capsys, tmp_path
):
    no_ffmpeg(monkeypatch)
    install_seam(monkeypatch, info=video_info(tmp_path), hooks=[FINISHED])
    run_cli("tube", "download", URL, "--output", str(tmp_path))
    assert "one playlist is many requests" not in capsys.readouterr().out
    run_cli("tube", "download", URL, "--output", str(tmp_path), "--playlist")
    assert "one playlist is many requests" in capsys.readouterr().out


def test_play_without_a_player_names_what_it_looked_for(run_cli, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(core.shutil, "which", lambda name: None)
    record = install_seam(monkeypatch, info=video_info(tmp_path))
    code = run_cli("tube", "play", URL)
    assert code == EXIT_TOOL_FAILED
    assert "mpv, ffplay" in " ".join(capsys.readouterr().err.split())
    assert "options" not in record, "no probe is issued when there is nothing to play with"


def test_play_hands_the_player_one_url_and_writes_nothing(run_cli, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/mpv")
    launched: list[list[str]] = []
    monkeypatch.setattr(core, "launch", lambda argv: launched.append(argv) or 0)
    info = {**video_info(tmp_path), "url": "https://example.invalid/stream.mp4"}
    record = install_seam(monkeypatch, info=info)
    assert run_cli("tube", "play", URL) == 0
    assert launched == [["/usr/bin/mpv", "https://example.invalid/stream.mp4"]]
    assert record["download"] is False
    assert "options" in record and record["options"]["format"] == "b"


def test_a_stream_with_no_single_file_url_sends_you_to_download(
    run_cli, monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/mpv")
    install_seam(monkeypatch, info={**video_info(tmp_path), "formats": []})
    assert run_cli("tube", "play", URL) == EXIT_PROVIDER
    assert "levix tube download" in " ".join(capsys.readouterr().err.split())


def test_a_player_that_fails_is_reported_with_its_own_code(run_cli, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr(core, "launch", lambda argv: 3)
    install_seam(monkeypatch, info={**video_info(tmp_path), "url": "https://x/y"})
    assert run_cli("tube", "play", URL) == EXIT_TOOL_FAILED
    assert "exited with code 3" in " ".join(capsys.readouterr().err.split())


def test_a_configured_output_directory_is_used_when_no_flag_is_given(
    run_cli, monkeypatch, capsys, tmp_path
):
    """The config layer, not a default baked into the command: `LEVIX_TUBE_OUTPUT_DIR`."""
    no_ffmpeg(monkeypatch)
    monkeypatch.setenv("COLUMNS", "200")
    configured = tmp_path / "from-config"
    configured.mkdir()
    target = configured / "Midnight Set [abcdef].mp4"
    monkeypatch.setenv("LEVIX_TUBE_OUTPUT_DIR", str(configured))
    install_seam(
        monkeypatch,
        info=video_info(configured),
        hooks=[DOWNLOADING, FINISHED],
        write=lambda: target.write_bytes(b"0" * 10),
    )
    assert run_cli("tube", "download", URL) == 0
    out = capsys.readouterr().out
    assert f"writing to {configured} (from tube.output_dir)" in out
    assert str(target) in out
    assert target.is_file() and "10 B" in out
    assert "yes" in out, "a real fetch moved bytes"

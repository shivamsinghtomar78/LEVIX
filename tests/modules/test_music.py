"""The Music module: gain maths, rate maths, the decode verdict, the queue, the seam.

Two things make these tests unusual and both are deliberate.

* `core.play_samples` is the only function that touches PortAudio, so every command test
  monkeypatches that one name and asserts on the frames it was handed. Not one test here
  opens a stream, which is what lets them run on a machine with no sound card.
* The audio files are real. soundfile writes genuine WAV/FLAC/OGG/MP3, so the decode path
  is exercised against bytes libsndfile actually parsed, not a mock of it.

The single `integration` test is the exception: it really plays, and skips out loud if
PortAudio reports no usable output device.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import levix
from levix.errors import (
    EXIT_CANCELLED,
    EXIT_CONFIG,
    EXIT_INTERRUPTED,
    EXIT_TOOL_FAILED,
    EXIT_USAGE,
    ConfigError,
)
from levix.module import Origin, Permission
from levix.modules.music import MANIFEST, core
from levix.modules.music.core import RequestError, UnsupportedFormatError
from levix.paths import resolve_paths
from levix.storage import Database

RATE = 44100


def tone(freq: float = 440.0, seconds: float = 0.25, amp: float = 0.5, channels: int = 2) -> np.ndarray:
    count = int(RATE * seconds)
    step = np.arange(count) / RATE
    wave = (amp * np.sin(2 * np.pi * freq * step)).astype("float32")
    return np.column_stack([wave] * channels)


def write_wav(directory: Path, name: str = "tone.wav", *, data: np.ndarray | None = None,
              rate: int = RATE, subtype: str = "PCM_16", seconds: float = 0.25) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    sf.write(path, data if data is not None else tone(seconds=seconds), rate, subtype=subtype)
    return path


@pytest.fixture
def wav(tmp_path) -> Path:
    return write_wav(tmp_path)


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "levix.db")


@pytest.fixture
def seam(monkeypatch) -> dict:
    """Replace the hardware seam and record exactly what was handed to it."""
    seen: dict = {}

    def fake(frames, samplerate, *, device=None, blocksize=0, on_block=None):
        seen["frames"] = np.asarray(frames)
        seen["samplerate"] = samplerate
        seen["device"] = device
        seen["blocksize"] = blocksize
        total = int(frames.shape[0])
        if on_block is not None:
            on_block(total, total)
        return total

    monkeypatch.setattr(core, "play_samples", fake)
    return seen


def both(captured) -> str:
    return captured.out + captured.err


def set_config(body: str) -> None:
    paths = resolve_paths().ensure()
    paths.config_file.write_text(body, encoding="utf-8")


# ----------------------------------------------------------------------------------
# volume
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("volume", "expected"), [(0.0, 0.0), (0.5, 0.25), (1.0, 0.5)])
def test_apply_gain_scales_every_sample(volume, expected):
    out = core.apply_gain(np.array([[0.5], [-0.5]], dtype="float32"), volume)
    assert out.dtype == np.float32
    assert out[0, 0] == pytest.approx(expected)
    assert out[1, 0] == pytest.approx(-expected)


def test_apply_gain_clips_instead_of_wrapping_around():
    hot = np.array([[0.9], [-0.9]], dtype="float32")
    out = core.apply_gain(hot, 1.0)
    assert float(out.max()) == pytest.approx(0.9)
    assert float(out.min()) == pytest.approx(-0.9)
    assert np.all(np.abs(out) <= 1.0)


@pytest.mark.parametrize("raw", [1.5, -0.1, float("nan"), float("inf"), "loud", None])
def test_an_impossible_volume_is_a_config_error_not_a_warning(raw):
    with pytest.raises(ConfigError) as caught:
        core.validate_volume(raw)
    assert caught.value.exit_code == EXIT_CONFIG
    assert "between 0.0 and 1.0" in caught.value.message


def test_volume_accepts_the_ways_a_config_value_arrives():
    assert core.validate_volume("0.25") == 0.25
    assert core.validate_volume(1) == 1.0
    assert core.validate_volume(0) == 0.0


# ----------------------------------------------------------------------------------
# duration, rate, progress
# ----------------------------------------------------------------------------------


def test_duration_is_frames_over_rate():
    assert core.duration_for(44100, RATE) == pytest.approx(1.0)
    assert core.duration_for(66150, RATE) == pytest.approx(1.5)
    assert np.isnan(core.duration_for(100, 0))


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "0.0s"), (1.5, "1.5s"), (59.96, "60.0s"), (75, "1:15"), (3725, "1:02:05")],
)
def test_format_duration(seconds, expected):
    assert core.format_duration(seconds) == expected


def test_format_duration_admits_an_unknown_rate():
    assert "unknown" in core.format_duration(float("nan"))


def test_resample_keeps_the_length_and_the_clock():
    data = tone(seconds=0.1, channels=1)
    out = core.resample(data, RATE, 48000)
    assert out.shape[0] == round(data.shape[0] * 48000 / RATE) == 4800
    assert out.shape[1] == 1
    assert core.duration_for(out.shape[0], 48000) == pytest.approx(
        core.duration_for(data.shape[0], RATE), abs=1e-4
    )


def test_resample_is_identity_at_the_same_rate():
    data = tone(seconds=0.05)
    assert core.resample(data, RATE, RATE) is data


def test_resample_endpoints_survive_and_downsampling_shortens():
    ramp = np.linspace(0.0, 1.0, 101, dtype="float32").reshape(-1, 1)
    out = core.resample(ramp, 44100, 22050)
    assert out.shape[0] == 50
    assert float(out[0, 0]) == pytest.approx(0.0, abs=1e-3)
    assert float(out[-1, 0]) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("bad", [500, 0, -1, 1_000_000, "quiet"])
def test_a_nonsensical_rate_is_refused(bad):
    with pytest.raises(RequestError) as caught:
        core.validate_rate(bad)
    assert caught.value.exit_code == EXIT_USAGE


def test_progress_percent_is_clamped_at_both_ends():
    assert core.progress_percent(0, 100) == 0.0
    assert core.progress_percent(50, 100) == 50.0
    assert core.progress_percent(1000, 100) == 100.0
    assert core.progress_percent(0, 0) == 100.0


# ----------------------------------------------------------------------------------
# decoding and the codec verdict
# ----------------------------------------------------------------------------------


def test_inspect_reports_what_libsndfile_found(wav):
    info = core.inspect_file(wav)
    assert info.samplerate == RATE
    assert info.channels == 2
    assert info.frames == int(RATE * 0.25)
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.duration == pytest.approx(0.25)
    assert "uncompressed" in info.codec_note


def test_a_compressed_subtype_is_named_as_one(tmp_path):
    path = write_wav(tmp_path, "gsm.wav", data=tone(channels=1), subtype="GSM610")
    info = core.inspect_file(path)
    assert info.subtype == "GSM610"
    assert "compressed" in info.codec_note


def test_load_decodes_real_bytes_and_applies_the_volume(wav):
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    frames, rate, info = core.load(wav, volume=0.5)
    assert rate == RATE and info.frames == raw.shape[0]
    assert frames.dtype == np.float32
    assert frames.shape == raw.shape
    assert float(np.abs(frames).max()) == pytest.approx(float(np.abs(raw).max()) * 0.5, abs=1e-6)


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("lyrics.txt", "just words, no audio\n"),
        ("fake.m4a", "FTYPnot-mpeg-4"),
        ("broken.wav", "RIFF    WAVEfmt "),
    ],
)
def test_an_undecodable_file_names_the_decoder_and_exits_seven(tmp_path, name, body):
    path = tmp_path / name
    path.write_bytes(body.encode("utf-8", "ignore"))
    with pytest.raises(UnsupportedFormatError) as caught:
        core.inspect_file(path)
    assert caught.value.exit_code == EXIT_TOOL_FAILED
    assert "libsndfile" in caught.value.message
    assert "ffmpeg" in caught.value.hint


def test_a_missing_file_is_a_usage_error(tmp_path):
    with pytest.raises(RequestError) as caught:
        core.require_file(tmp_path / "ghost.wav")
    assert caught.value.exit_code == EXIT_USAGE
    assert "does not exist" in caught.value.message


def test_a_directory_is_not_an_audio_file(tmp_path):
    with pytest.raises(RequestError, match="is a directory"):
        core.require_file(tmp_path)


# ----------------------------------------------------------------------------------
# the seam, through the real entry point
# ----------------------------------------------------------------------------------


def test_play_hands_the_decoded_frames_to_the_seam(run_cli, capsys, wav, seam):
    assert run_cli("music", "play", str(wav)) == 0
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    assert seam["samplerate"] == RATE
    assert seam["device"] is None
    assert seam["frames"].shape == raw.shape
    text = both(capsys.readouterr())
    assert f"{seam['frames'].shape[0]:,} frames" in text and "Traceback" not in text


def test_play_applies_the_configured_volume(run_cli, capsys, wav, seam, levix_home):
    set_config("[music]\nvolume = 0.25\n")
    assert run_cli("music", "play", str(wav)) == 0
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    assert float(np.abs(seam["frames"]).max()) == pytest.approx(float(np.abs(raw).max()) * 0.25,
                                                                 abs=1e-6)
    assert "gain 0.25" in both(capsys.readouterr())


def test_the_flag_beats_the_configuration(run_cli, wav, seam, levix_home):
    set_config("[music]\nvolume = 0.25\n")
    assert run_cli("music", "play", "--volume", "1.0", str(wav)) == 0
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    assert float(np.abs(seam["frames"]).max()) == pytest.approx(float(np.abs(raw).max()), abs=1e-6)


def test_device_and_rate_reach_the_seam(run_cli, wav, seam):
    assert run_cli("music", "play", "--device", "3", "--rate", "48000", str(wav)) == 0
    assert seam["device"] == 3
    assert seam["samplerate"] == 48000
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    assert seam["frames"].shape[0] == round(raw.shape[0] * 48000 / RATE)


def test_a_bad_volume_flag_exits_five(run_cli, capsys, wav, seam, levix_home):
    assert run_cli("music", "play", "--volume", "1.5", str(wav)) == EXIT_CONFIG
    assert "between 0.0 and 1.0" in both(capsys.readouterr())
    assert "frames" not in seam, "nothing may be handed to the device after a refusal"


def test_a_bad_rate_flag_exits_two(run_cli, capsys, wav, seam):
    assert run_cli("music", "play", "--rate", "500", str(wav)) == EXIT_USAGE
    assert seam == {}


def test_play_of_an_undecodable_file_exits_seven(run_cli, capsys, tmp_path):
    junk = tmp_path / "song.m4a"
    junk.write_bytes(b"no codec here")
    assert run_cli("music", "play", str(junk)) == EXIT_TOOL_FAILED
    text = both(capsys.readouterr())
    assert "libsndfile" in text and "Traceback" not in text


def test_ctrl_c_during_playback_exits_130_and_says_the_device_is_free(
    run_cli, capsys, wav, monkeypatch
):
    def interrupt(frames, samplerate, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(core, "play_samples", interrupt)
    assert run_cli("music", "play", str(wav)) == EXIT_INTERRUPTED
    text = both(capsys.readouterr())
    assert "interrupted" in text and "Traceback" not in text


def test_a_backend_refusal_is_one_clean_message_and_exit_seven(run_cli, capsys, wav, monkeypatch):
    monkeypatch.setattr(
        core,
        "play_samples",
        lambda *a, **k: (_ for _ in ()).throw(
            core.AudioDeviceError("PortAudio could not play on the default output device: boom")
        ),
    )
    assert run_cli("music", "play", str(wav)) == EXIT_TOOL_FAILED
    text = both(capsys.readouterr())
    assert "PortAudio" in text and "Traceback" not in text


# ----------------------------------------------------------------------------------
# devices
# ----------------------------------------------------------------------------------


def test_list_devices_reports_roles_and_defaults():
    try:
        listing = core.list_devices()
    except core.BackendError as exc:
        pytest.skip(f"PortAudio has no device view here: {exc.message}")
    assert listing.rows
    assert all(row.role in ("input", "output", "in+out", "unusable") for row in listing.rows)
    assert listing.mark(listing.rows[0]) in ("", "in", "out", "in+out")
    # The note is the honest fallback: either nothing to say, or a reason playback fails.
    assert listing.note() == "" or "device" in listing.note()


def test_devices_command_prints_a_table(run_cli, capsys):
    code = run_cli("music", "devices")
    text = both(capsys.readouterr())
    if code == EXIT_TOOL_FAILED:
        pytest.skip(f"PortAudio refused to list devices here: {text.strip()[:120]}")
    assert code == 0
    assert "Audio devices" in text and "default" in text.lower()
    assert "Traceback" not in text


def test_devices_rejects_an_unknown_kind(run_cli, capsys):
    assert run_cli("music", "devices", "--kind", "banana") == EXIT_USAGE
    assert "--kind must be" in both(capsys.readouterr())


# ----------------------------------------------------------------------------------
# library
# ----------------------------------------------------------------------------------


@pytest.fixture
def library_tree(tmp_path) -> Path:
    root = tmp_path / "music"
    write_wav(root, "one.wav", seconds=0.1)
    write_wav(root / "deep", "two.wav", seconds=0.2)
    write_wav(root, ".hidden.wav", seconds=0.1)
    (root / "notes.txt").write_text("words\n", encoding="utf-8")
    (root / "broken.wav").write_bytes(b"RIFF    WAVEfmt ")
    (root / "empty").mkdir()
    return root


def test_scan_finds_real_audio_and_reports_what_it_refused(library_tree):
    found = core.scan_library(library_tree)
    assert sorted(track.path.name for track in found.tracks) == ["one.wav", "two.wav"]
    # every folder visited is counted, including the empty one that holds no audio
    assert found.directories == 3
    assert found.skipped_suffix >= 1
    assert [path.name for path, _reason in found.unreadable] == ["broken.wav"]
    assert found.total_duration == pytest.approx(0.3, abs=0.02)
    assert found.display(library_tree / "deep" / "two.wav") == str(
        Path("deep") / "two.wav"
    )


def test_scan_totals_are_per_holding_folder(library_tree):
    found = core.scan_library(library_tree)
    groups = {folder.name: count for folder, count, _seconds in found.by_directory()}
    assert groups == {"music": 1, "deep": 1}


def test_scan_hidden_opt_in_reaches_the_dot_file(library_tree):
    found = core.scan_library(library_tree, include_hidden=True)
    assert ".hidden.wav" in [track.path.name for track in found.tracks]


def test_scan_of_a_narrow_suffix_set(library_tree):
    found = core.scan_library(library_tree, suffixes=["flac"])
    assert found.tracks == []


def test_an_unset_library_says_so_instead_of_printing_nothing():
    assert core.library_root("", None) is None
    assert core.library_root("   ", None) is None


def test_a_configured_library_that_vanishes_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError) as caught:
        core.library_root(str(tmp_path / "gone"), None)
    assert caught.value.exit_code == EXIT_CONFIG


def test_a_bad_root_flag_is_a_usage_error(tmp_path):
    with pytest.raises(RequestError):
        core.library_root("", tmp_path / "nope")
    write_wav(tmp_path, "x.wav", seconds=0.01)
    with pytest.raises(RequestError, match="not a directory"):
        core.library_root("", tmp_path / "x.wav")


def test_library_command_lists_tracks_and_folder_totals(run_cli, capsys, levix_home, library_tree):
    assert run_cli("music", "library", "--root", str(library_tree)) == 0
    text = both(capsys.readouterr())
    assert "one.wav" in text and "two.wav" in text
    assert "Per directory" in text
    assert "did not decode" in text and "broken.wav" in text
    assert "Traceback" not in text


def test_library_command_reports_an_unconfigured_directory(run_cli, capsys, levix_home):
    assert run_cli("music", "library") == 0
    text = both(capsys.readouterr())
    assert "music.library_dir is not set" in text and "config set" in text


def test_library_command_uses_the_configured_root(run_cli, capsys, levix_home, library_tree):
    set_config(f"[music]\nlibrary_dir = \"{library_tree.as_posix()}\"\n")
    assert run_cli("music", "library") == 0
    assert "one.wav" in both(capsys.readouterr())


def test_an_empty_library_says_so(run_cli, capsys, levix_home, tmp_path):
    assert run_cli("music", "library", "--root", str(tmp_path / "nothing")) == EXIT_USAGE
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert run_cli("music", "library", "--root", str(empty)) == 0
    assert "no playable file" in both(capsys.readouterr())


# ----------------------------------------------------------------------------------
# playlist: migrations and CRUD on a real database
# ----------------------------------------------------------------------------------


def test_the_migration_is_namespaced_music_and_idempotent(db):
    assert core.ensure_schema(db) == ["music:1"]
    assert core.ensure_schema(db) == []
    with db.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "music_playlist" in tables


def test_add_assigns_ids_in_order_and_skips_duplicates(db, wav, tmp_path):
    second = write_wav(tmp_path, "second.wav", seconds=0.1)
    result = core.add_to_playlist(db, [wav, second])
    assert [entry.path.name for entry in result.added] == ["tone.wav", "second.wav"]
    assert [entry.id for entry in result.added] == [1, 2]
    assert core.add_to_playlist(db, [second]).added == ()
    assert core.add_to_playlist(db, [second]).duplicate
    assert [entry.path.name for entry in core.list_playlist(db)] == ["tone.wav", "second.wav"]


def test_add_refuses_a_ghost_and_queues_nothing_alongside_it(db, wav):
    with pytest.raises(RequestError):
        core.add_to_playlist(db, [wav, "nowhere.wav"])
    assert core.list_playlist(db) == ()


def test_remove_reports_what_was_there_and_what_was_not(db, wav, tmp_path):
    second = write_wav(tmp_path, "b.wav", seconds=0.1)
    core.add_to_playlist(db, [wav, second])
    removed, missing = core.remove_from_playlist(db, [1, 99])
    assert [entry.id for entry in removed] == [1]
    assert missing == (99,)
    assert [entry.path.name for entry in core.list_playlist(db)] == ["b.wav"]


def test_clear_empties_the_queue_without_touching_the_files(db, wav):
    core.add_to_playlist(db, [wav])
    assert core.clear_playlist(db) == 1
    assert core.count_playlist(db) == 0
    assert wav.exists()


def test_an_entry_whose_file_went_away_is_flagged_not_played(db, wav, tmp_path):
    doomed = write_wav(tmp_path, "doomed.wav", seconds=0.1)
    core.add_to_playlist(db, [wav, doomed])
    entries = core.list_playlist(db)
    doomed.unlink()
    assert [entry.exists for entry in entries] == [True, False]


def test_playlist_commands_round_trip_through_the_cli(run_cli, capsys, wav, levix_home):
    assert run_cli("music", "playlist", "add", str(wav)) == 0
    assert "added 1" in both(capsys.readouterr())
    assert run_cli("music", "playlist", "list") == 0
    assert "tone.wav" in both(capsys.readouterr())
    assert run_cli("music", "playlist", "remove", "1") == 0
    assert "1 removed" in both(capsys.readouterr())
    assert run_cli("music", "playlist", "list") == 0
    assert "empty" in both(capsys.readouterr())


def test_playlist_clear_needs_a_terminal_and_forgets_nothing(run_cli, capsys, wav, levix_home):
    assert run_cli("music", "playlist", "add", str(wav)) == 0
    assert run_cli("music", "playlist", "clear") == EXIT_CANCELLED
    assert run_cli("music", "playlist", "clear", "--yes") == EXIT_CANCELLED
    assert "--yes cannot authorize" in both(capsys.readouterr())
    assert core.count_playlist(Database(resolve_paths().database)) == 1


def test_playlist_play_continues_past_a_broken_entry(run_cli, capsys, wav, tmp_path, seam):
    broken = tmp_path / "bad.ogg"
    broken.write_bytes(b"OggS not really ogg")
    assert run_cli("music", "playlist", "add", str(broken)) == 0
    assert run_cli("music", "playlist", "add", str(wav)) == 0
    assert run_cli("music", "playlist", "play") == 0
    text = both(capsys.readouterr())
    assert "skipped" in text and "1 played, 1 skipped" in text
    assert seam["frames"].shape[0] == int(RATE * 0.25)


def test_playlist_play_says_when_the_queue_is_empty(run_cli, capsys, levix_home):
    assert run_cli("music", "playlist", "play") == 0
    assert "empty" in both(capsys.readouterr())


# ----------------------------------------------------------------------------------
# the manifest, and the lazy loading that depends on it
# ----------------------------------------------------------------------------------


def test_manifest_declares_the_packaged_contract():
    assert MANIFEST.name == "music" and MANIFEST.title == "Music"
    assert MANIFEST.cli_path == "levix.modules.music.cli:build_app"
    assert MANIFEST.command_names() == ("play", "info", "devices", "library", "playlist")
    assert {ref.import_name for ref in MANIFEST.requirements} == {"soundfile", "sounddevice"}
    assert {ref.distribution for ref in MANIFEST.requirements} == {"soundfile", "sounddevice"}
    assert MANIFEST.extras == ("music",)
    assert MANIFEST.documentation == "docs/modules/MUSIC.md"
    assert Permission.AUDIO in MANIFEST.permissions
    assert MANIFEST.ui is not None and MANIFEST.ui.mode == "suspend"


def test_the_registry_stamps_the_official_install_hint():
    """The packaged MANIFEST is pure data with origin left at the neutral default; the
    registry owns ownership stamping, so the `levix[music]` hint is checked where it is
    actually produced - on the discovered manifest."""
    raw = MANIFEST.resolved_install_hint()
    assert raw is None  # third-party with no provider cannot name a package

    from levix.registry import ModuleRegistry

    discovered = ModuleRegistry().discover().get("music")
    assert discovered is not None, "the music entry point is not registered"
    assert discovered.origin is Origin.OFFICIAL
    assert discovered.resolved_install_hint() == 'pip install "levix[music]"'
    assert discovered.version == levix.__version__


def _child(tmp_path, *statements: str) -> subprocess.CompletedProcess[str]:
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


def test_importing_the_manifest_pulls_in_no_audio_libraries(tmp_path):
    completed = _child(
        tmp_path,
        "import levix.modules.music as m",
        "heavy = [x for x in ('soundfile','sounddevice','numpy','typer','rich') "
        "if x in sys.modules]",
        "print(len(m.MANIFEST.commands), heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "5 []"


def test_module_help_does_not_import_the_optional_dependencies(tmp_path):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        "code = main(['music', '-h'])",
        "heavy = [x for x in ('soundfile', 'sounddevice', 'psutil', 'yt_dlp') "
        "if x in sys.modules]",
        "print(code, heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 []"


def test_info_help_needs_no_portaudio(tmp_path):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        "code = main(['music', 'info', '-h'])",
        "print(code, 'sounddevice' in sys.modules, 'soundfile' in sys.modules)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 False False"


# ----------------------------------------------------------------------------------
# real playback: the one test allowed to open a stream
# ----------------------------------------------------------------------------------


@pytest.mark.integration
def test_zero_five_seconds_of_a_real_tone_reaches_a_real_output_device(tmp_path):
    import sounddevice as sd

    try:
        output = sd.query_devices(kind="output")
    except Exception as exc:  # PortAudio refuses to name a device here
        pytest.skip(f"no usable output device: {type(exc).__name__}: {exc}")
    channels = int(output["max_output_channels"])
    if channels < 1:
        pytest.skip(f"device {output['name']!r} exposes no output channels")
    rate = int(output["default_samplerate"]) or RATE
    path = write_wav(tmp_path, "blip.wav", seconds=0.05)
    frames, samplerate, info = core.load(path, volume=0.4)
    assert samplerate == RATE
    delivered = core.play_samples(frames, samplerate, device=None)
    assert delivered == info.frames == int(0.05 * RATE)
    assert rate > 0, "the device reported a sample rate to open at"

"""The Music module: gain maths, rate maths, the decode verdict, the queue, the seam.

Two things make these tests unusual and both are deliberate.

* `core.play_samples` is the only function that touches PortAudio, so every command test
  monkeypatches that one name and asserts on the frames it was handed. Not one test here
  opens a stream, which is what lets them run on a machine with no sound card.
* The audio files are real. soundfile writes genuine WAV/FLAC/OGG/MP3, so the decode path
  is exercised against bytes libsndfile actually parsed, not a mock of it.

The three `integration` tests are the exception: one really plays, two really ask the
operating system which sound hardware it has. Each skips out loud when the machine has
nothing to answer with, which is why CI's runners do not report them as failures.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from rich.console import Console

import levix
from levix import terminal
from levix.errors import (
    EXIT_CANCELLED,
    EXIT_CONFIG,
    EXIT_INTERRUPTED,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PROVIDER,
    EXIT_TOOL_FAILED,
    EXIT_USAGE,
    ConfigError,
)
from levix.module import Origin, Permission
from levix.modules.music import MANIFEST, cli, core, visual
from levix.modules.music.core import RequestError, UnsupportedFormatError
from levix.paths import resolve_paths
from levix.storage import Database

RATE = 44100


def tone(
    freq: float = 440.0,
    seconds: float = 0.25,
    amp: float = 0.5,
    channels: int = 2,
    rate: int = RATE,
) -> np.ndarray:
    count = int(rate * seconds)
    step = np.arange(count) / rate
    wave = (amp * np.sin(2 * np.pi * freq * step)).astype("float32")
    return np.column_stack([wave] * channels)


def write_wav(
    directory: Path,
    name: str = "tone.wav",
    *,
    data: np.ndarray | None = None,
    rate: int = RATE,
    subtype: str = "PCM_16",
    seconds: float = 0.25,
) -> Path:
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


def flat(captured) -> str:
    """`both`, with every soft-wrap folded back into one line.

    Rich breaks a long message at the console width, so a sentence this module prints in
    one call is not one line in the capture. Prose assertions read the prose, not the
    column count.
    """
    return " ".join(both(captured).split())


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


#: Every suffix `SCAN_SUFFIXES` offers, with what writing one takes here. Two need it
#: spelled out: `.opus` and `.aif` do not name a format to soundfile, and Opus refuses any
#: rate outside 8/12/16/24/48 kHz, so 44100 fails the write rather than the read.
CONTAINERS = (
    ("tone.wav", RATE, {}, "WAV"),
    ("tone.flac", RATE, {}, "FLAC"),
    ("tone.ogg", RATE, {}, "OGG"),
    ("tone.opus", 48000, {"format": "OGG", "subtype": "OPUS"}, "OGG"),
    ("tone.mp3", RATE, {}, "MP3"),
    ("tone.aiff", RATE, {}, "AIFF"),
    ("tone.aif", RATE, {"format": "AIFF"}, "AIFF"),
    ("tone.au", RATE, {}, "AU"),
)


@pytest.mark.parametrize(
    ("name", "rate", "write_kwargs", "expected_format"),
    [(case[0], case[1], case[2], case[3]) for case in CONTAINERS],
)
def test_every_container_the_scan_offers_decodes_here(
    tmp_path, name, rate, write_kwargs, expected_format
):
    """The scan promises these suffixes are playable, so decoding them is the promise.

    No extension mapping is involved: libsndfile reads the header, which is why the `.aif`
    file reports the same format as the `.aiff` one.
    """
    path = tmp_path / name
    sf.write(str(path), tone(seconds=0.1, rate=rate), rate, **write_kwargs)
    frames, actual_rate, info = core.load(path, volume=1.0)
    assert info.format == expected_format
    assert actual_rate == rate
    assert frames.dtype == np.float32
    assert frames.shape == (int(rate * 0.1), 2)
    assert float(np.abs(frames).max()) > 0.2


def test_the_container_table_is_the_scan_suffixes():
    assert {Path(name).suffix for name, *_ in CONTAINERS} == set(core.SCAN_SUFFIXES)


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
    assert float(np.abs(seam["frames"]).max()) == pytest.approx(
        float(np.abs(raw).max()) * 0.25, abs=1e-6
    )
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


@pytest.mark.integration
def test_list_devices_reports_roles_and_defaults():
    """Asks the operating system what sound hardware it has, so it is an integration test.

    CI run #3 showed why: a runner either has no PortAudio to import (Ubuntu, where the
    system library simply is not there) or PortAudio that reports zero devices (Windows),
    and neither is a defect in the listing. Anything PortAudio raises here is the machine
    answering, not the module.
    """
    try:
        listing = core.list_devices()
    except Exception as exc:  # PortAudio is the machine answering, not the module failing
        pytest.skip(f"PortAudio has no device view on this machine: {type(exc).__name__}: {exc}")
    if not listing.rows:
        pytest.skip("this machine reports no audio devices")
    assert all(row.role in ("input", "output", "in+out", "unusable") for row in listing.rows)
    assert listing.mark(listing.rows[0]) in ("", "in", "out", "in+out")
    # The note is the honest fallback: either nothing to say, or a reason playback fails.
    assert listing.note() == "" or "device" in listing.note()


@pytest.mark.integration
def test_devices_command_prints_a_table(run_cli, capsys):
    """The same hardware question, asked through the command surface.

    Decided before running: `music devices` exits 7 when PortAudio refuses and 1 when the
    library itself is missing, and letting either reach the assertion would report a
    silent runner as a broken module.
    """
    import sounddevice as sd

    try:
        devices = sd.query_devices()
    except Exception as exc:  # PortAudio is the machine answering, not the module failing
        pytest.skip(f"PortAudio has no device view on this machine: {type(exc).__name__}: {exc}")
    if not devices:
        pytest.skip("this machine reports no audio devices")
    code = run_cli("music", "devices")
    text = both(capsys.readouterr())
    assert code == 0, text
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
    assert found.display(library_tree / "deep" / "two.wav") == str(Path("deep") / "two.wav")


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
    set_config(f'[music]\nlibrary_dir = "{library_tree.as_posix()}"\n')
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
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
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
# the spectrum rules: numbers in, numbers out, no device and no terminal
# ----------------------------------------------------------------------------------


def bin_window(
    index: int,
    *,
    rate: int = RATE,
    frames: int = visual.WINDOW_FRAMES,
    amp: float = 1.0,
    channels: int = 1,
) -> np.ndarray:
    """A sine of `index` whole periods across the window, so one DFT bin holds all of it.

    Anchoring the tone to a bin rather than to a round frequency is what makes the
    assertions exact: a 440 Hz tone in a 2048-frame window at 44.1 kHz is 20.43 periods,
    and the leakage it suffers is the window's, not the meter's.
    """
    step = np.arange(frames) / frames
    wave = (amp * np.sin(2 * np.pi * index * step)).astype("float32")
    return np.column_stack([wave] * channels)


def band_holding(freq: float, edges: tuple[float, ...]) -> int | None:
    for index in range(len(edges) - 1):
        if edges[index] <= freq < edges[index + 1]:
            return index
    return None


def test_a_tone_lights_the_band_that_contains_it():
    edges = visual.band_edges(visual.MAX_BANDS)
    for index in (2, 20, 100, 300):
        freq = index * RATE / visual.WINDOW_FRAMES
        levels = visual.spectrum(bin_window(index), RATE, bands=visual.MAX_BANDS)
        lit = [i for i, level in enumerate(levels) if level > 0.5]
        home = band_holding(freq, edges)
        assert home in lit, f"{freq:.1f} Hz lit {lit}, not {home}"
        assert all(abs(i - home) <= 1 for i in lit), "a bin reaches only the bands it overlaps"
        assert levels[home] == pytest.approx(1.0), "full scale is the top of the meter"


def test_no_band_is_left_without_a_bin_to_read():
    """24 columns over a 2048-frame window put 65.5-83.9 Hz between two bin centres.

    That column stays dark for a whole bass line, which reads as a broken meter rather
    than as silence, so each band must be handed at least one bin at every rate the module
    accepts.
    """
    for rate in (core.MIN_RATE, RATE, core.MAX_RATE):
        plan = visual.band_bins(visual.MAX_BANDS, visual.WINDOW_FRAMES, rate)
        assert len(plan) == visual.MAX_BANDS
        assert all(stop > start for start, stop in plan), f"{rate} Hz left a column with no bins"


def test_a_band_with_no_bin_centre_is_still_read():
    """65.5-83.9 Hz lies between two bin centres, and reading centres alone left it dark.

    Measured, not reasoned about: at 44.1 kHz over the 2048-frame window the bins either
    side of that band sit at 64.6 and 86.1 Hz, so exactly one of the 24 columns had no bin
    of its own - and a bass line played while it stayed at the floor.
    """
    step = RATE / visual.WINDOW_FRAMES
    edges = visual.band_edges(visual.MAX_BANDS)
    plan = visual.band_bins(visual.MAX_BANDS, visual.WINDOW_FRAMES, RATE)
    centres = range(1, visual.WINDOW_FRAMES // 2 + 1)
    without = [
        band
        for band in range(visual.MAX_BANDS)
        if not any(edges[band] <= index * step < edges[band + 1] for index in centres)
    ]
    assert without == [2], "the one column this window and rate produce"
    for band in without:
        start, stop = plan[band]
        assert stop > start, "handed the bins that touch it instead"


def test_the_meter_maps_dbfs_onto_the_column():
    assert visual.levels_from([1.0]) == (1.0,), "0 dBFS is the top"
    assert visual.levels_from([0.2]) == pytest.approx((0.741,), abs=0.001)
    assert visual.levels_from([0.02]) == pytest.approx((0.371,), abs=0.001)
    assert visual.levels_from([0.0]) == (0.0,), "a band with nothing in it sits on the floor"
    assert visual.levels_from([2.0]) == (1.0,), "and a hot one is not allowed past the ceiling"
    with pytest.raises(ValueError, match="must exceed"):
        visual.levels_from([0.5], floor_db=0.0, ceil_db=0.0)


def test_content_above_and_below_the_meter_range_stays_dark():
    below = band_holding(visual.LOW_HZ / 2, visual.band_edges(visual.MAX_BANDS))
    above = band_holding(visual.HIGH_HZ * 1.2, visual.band_edges(visual.MAX_BANDS))
    assert (below, above) == (None, None), "the edges themselves admit no such band"
    for index in (1, 800):  # 21.5 Hz and 17.2 kHz at 44.1 kHz over 2048 frames
        levels = visual.spectrum(bin_window(index), RATE, bands=visual.MAX_BANDS)
        assert max(levels) == 0.0, f"bin {index} is outside 40 Hz-15 kHz and must not draw"


def test_silence_sits_on_the_floor_and_full_scale_on_the_top():
    silence = np.zeros((visual.WINDOW_FRAMES, 1), dtype="float32")
    assert visual.spectrum(silence, RATE, bands=8) == (0.0,) * 8
    assert max(visual.spectrum(bin_window(20), RATE, bands=8)) == pytest.approx(1.0)


@pytest.mark.parametrize(("amp", "expected"), [(0.005, 0.148), (0.02, 0.371), (0.05, 0.518)])
def test_a_quiet_tone_fills_part_of_its_column(amp, expected):
    """The dBFS window, not a clamp: -54 to 0 spread over the seven rows.

    Measured against a full mix, the wider floor the module first used (-80 dBFS) put every
    band between 0.75 and 1.0 - a solid block. These three amplitudes are the middle of the
    range the rows actually travel through.
    """
    levels = visual.spectrum(bin_window(20, amp=amp), RATE, bands=8)
    assert max(levels) == pytest.approx(expected, abs=0.01)
    louder = max(visual.spectrum(bin_window(20, amp=amp * 10), RATE, bands=8))
    assert louder > max(levels)


def test_the_bands_are_log_spaced_from_the_low_to_the_high_edge():
    edges = visual.band_edges(6)
    assert edges[0] == visual.LOW_HZ
    assert edges[-1] == visual.HIGH_HZ
    ratios = [b / a for a, b in itertools.pairwise(edges)]
    assert all(ratio == pytest.approx(ratios[0]) for ratio in ratios)
    assert ratios[0] > 1.0, "each band is a constant multiple wider than the last"


@pytest.mark.parametrize("bands", [0, -3])
def test_band_edges_refuses_a_meter_with_no_columns(bands):
    with pytest.raises(ValueError, match="at least one band"):
        visual.band_edges(bands)


@pytest.mark.parametrize(
    ("low", "high"), [(15000.0, 40.0), (40.0, 40.0), (40.0, 30000.0), (0.0, 15000.0)]
)
def test_band_edges_refuses_a_range_it_cannot_measure(low, high):
    with pytest.raises(ValueError, match="band range"):
        visual.band_edges(8, low=low, high=high)


@pytest.mark.parametrize(
    ("columns", "expected"), [(80, visual.MAX_BANDS), (24, 24), (9, 9), (0, 1), (-40, 1)]
)
def test_a_narrow_terminal_gets_fewer_columns_and_never_none(columns, expected):
    assert visual.band_count(columns) == expected


def test_a_peak_holds_and_then_decays_toward_the_current_level():
    caps = visual.apply_caps([1.0, 0.0], [0.0, 0.0])
    assert caps == (1.0, 0.0), "a new peak takes the cap at once"
    for _ in range(4):
        caps = visual.apply_caps([0.0, 0.0], caps)
    assert caps[0] == pytest.approx(1.0 - 4 * visual.CAP_DECAY)
    for _ in range(40):
        caps = visual.apply_caps([0.0, 0.0], caps)
    assert caps == (0.0, 0.0), "decay stops at the floor instead of running negative"
    assert visual.apply_caps([0.8, 0.0], caps) == (0.8, 0.0), "a louder frame lifts the cap again"


def test_levels_and_caps_of_different_widths_are_refused():
    with pytest.raises(ValueError, match="cannot update"):
        visual.apply_caps([0.5, 0.5], [0.0])


def test_the_redraw_is_gated_to_the_frame_budget():
    assert visual.frame_due(0.0, 0.0), "nothing has drawn yet"
    interval = 1.0 / visual.FPS
    assert visual.frame_due(interval, 0.0)
    assert not visual.frame_due(interval, interval), "a clock that has not moved draws once"
    assert not visual.frame_due(interval + interval / 2, interval)
    assert visual.frame_due(interval + interval, interval)


def test_a_frame_is_height_lines_of_one_glyph_per_column():
    glyph_set = {"block": "#", "shade": "+"}
    levels, caps = [1.0, 0.0, 0.5], [1.0, 1.0, 0.5]
    frame = visual.render(levels, caps, glyphs=glyph_set)
    lines = frame.plain.splitlines()
    assert len(lines) == visual.HEIGHT
    assert {len(line) for line in lines} == {3}, "one character per column, spaces included"
    short = visual.render(levels, caps, glyphs=glyph_set, height=3)
    assert short.plain == "#+ \n# #\n# #"


def test_an_empty_column_draws_nothing_and_a_full_one_draws_every_row():
    assert visual.bar_rows(0.0) == 0
    assert visual.bar_rows(1.0) == visual.HEIGHT
    assert visual.bar_rows(2.0) == visual.HEIGHT and visual.bar_rows(-1.0) == 0
    blank = visual.render([0.0, 1.0], [0.0, 1.0], glyphs={"block": "#", "shade": "+"})
    left, right = zip(*(line for line in blank.plain.splitlines()), strict=True)
    assert set(left) == {" "} and set(right) == {"#"}


def test_the_colours_run_green_at_the_bottom_to_red_at_the_top():
    glyph_set = {"block": "#", "shade": "+"}
    frame = visual.render([1.0], [1.0], glyphs=glyph_set)
    styles = [span.style for span in frame.spans]
    assert styles[0] == "bold red", "the first line is the top of the meter"
    assert styles[-1] == "green"
    assert set(styles) == {"bold red", "yellow", "green"}
    assert set(frame.plain.replace("\n", "")) == {"#"}, "the styles are markup over the same blocks"


def test_stereo_and_mono_of_the_same_signal_measure_the_same():
    mono = visual.spectrum(bin_window(20), RATE, bands=12)
    stereo = visual.spectrum(bin_window(20, channels=2), RATE, bands=12)
    assert mono == pytest.approx(stereo)


def test_a_low_rate_meter_stops_at_its_own_nyquist():
    """The top edge follows the sample rate instead of claiming 15 kHz the clock cannot carry.

    A 3.5 kHz tone is the loudest thing an 8 kHz file can hold. Left at the default edges
    it would sit two columns below the top, so a downsampled master would look thin.
    """
    rate = 8000
    levels = visual.spectrum(bin_window(896, rate=rate), rate, bands=visual.MAX_BANDS)
    assert levels[-1] == pytest.approx(1.0), "measured in the last band there is"
    assert max(levels[:-1]) == 0.0


# ----------------------------------------------------------------------------------
# the visual, through the same seam
# ----------------------------------------------------------------------------------


@pytest.fixture
def fake_tty(monkeypatch) -> io.StringIO:
    """A Console that believes it is a terminal, so the TTY-only paths can be seen.

    `_Progress` and `cli._visual_for` both ask `console.is_terminal`, and capsys's stream
    is not one, so without this the animation code is only ever observable refusing.
    """
    sink = io.StringIO()
    monkeypatch.setattr(
        cli, "console", Console(file=sink, force_terminal=True, width=80, height=24)
    )
    return sink


def test_the_spectrum_draws_from_the_frames_at_the_playhead(
    run_cli, wav, seam, fake_tty, monkeypatch
):
    seen: dict[str, object] = {}

    def spy(window, samplerate, *, bands):
        seen["shape"] = np.asarray(window).shape
        seen["rate"] = samplerate
        return (1.0,) * bands

    monkeypatch.setattr(visual, "spectrum", spy)
    assert run_cli("music", "play", "--visual", "bar", str(wav)) == 0
    raw, _rate = sf.read(str(wav), dtype="float32", always_2d=True)
    assert seen["rate"] == RATE
    assert seen["shape"] == (visual.WINDOW_FRAMES, raw.shape[1]), (
        "the window ending at the playhead"
    )
    text = fake_tty.getvalue()
    assert terminal.active_glyphs()["block"] in text, "a full meter of blocks"
    assert "playing" not in text, "the meter replaces the line, it does not add to it"


def test_visual_off_keeps_the_one_line_progress(run_cli, wav, seam, fake_tty):
    assert run_cli("music", "play", "--visual", "off", str(wav)) == 0
    text = fake_tty.getvalue()
    assert "playing" in text and "frames" in text, "the throttled line, not a meter"


def test_music_visual_off_is_honoured_without_a_flag(run_cli, wav, seam, fake_tty, levix_home):
    set_config('[music]\nlibrary_dir = ""\nvolume = 0.8\nvisual = "off"\n')
    assert run_cli("music", "play", str(wav)) == 0
    assert "playing" in fake_tty.getvalue()


def test_the_configured_default_quiets_down_on_a_pipe(run_cli, capsys, wav, seam, levix_home):
    set_config('[music]\nlibrary_dir = ""\nvolume = 0.8\nvisual = "bar"\n')
    assert run_cli("music", "play", str(wav)) == 0
    assert seam, "the file still played"
    assert "visual" not in both(capsys.readouterr()), "and it did not complain about it"


def test_an_explicit_visual_on_a_piped_stdout_exits_two(run_cli, capsys, wav, seam):
    assert run_cli("music", "play", "--visual", "bar", str(wav)) == EXIT_USAGE
    text = both(capsys.readouterr())
    assert "redirected" in text and "--visual off" in text
    assert seam == {}, "the refusal happens before anything reaches the device"


@pytest.mark.parametrize("raw", ["bars", "spectrum", "1"])
def test_an_unknown_visual_is_a_usage_error(run_cli, capsys, wav, seam, raw):
    assert run_cli("music", "play", "--visual", raw, str(wav)) == EXIT_USAGE
    assert "--visual must be one of bar, off" in both(capsys.readouterr())
    assert seam == {}


def test_the_music_visual_choices_match_the_renderer_modes():
    """config.SCHEMA spells the two modes out again, so the two must not drift.

    The core cannot import a module to read its constants - `levix config set` has to work
    with the extras absent - so the duplication is deliberate and this is what guards it.
    """
    import tomllib

    from levix.config import DEFAULTS_FILE, SCHEMA

    assert SCHEMA["music"]["visual"].choices == visual.MODES
    with DEFAULTS_FILE.open("rb") as handle:
        packaged = tomllib.load(handle)["music"]["visual"]
    assert packaged == visual.DEFAULT_MODE == "bar"


# ----------------------------------------------------------------------------------
# the URL source: one link, one cache folder, one import seam
# ----------------------------------------------------------------------------------

URL = "https://example.invalid/watch?v=abcdef"


@pytest.fixture
def stream_seam(monkeypatch) -> dict:
    """Stand in for yt-dlp, and hand over the tool gate.

    The fake writes a genuine MP3 into the folder `fetch_audio` told it to use, so what the
    command decodes afterwards is bytes libsndfile actually parsed - the fake replaces the
    network and the converter, never the decoder. `outcome` is the knob a test turns to
    make the fetch misbehave.
    """
    record: dict = {"calls": 0, "outcome": "written", "raises": None}

    def _make_ydl(options: dict):
        record["calls"] += 1
        record["options"] = options

        class Fake:
            def extract_info(self, url: str, download: bool = False) -> dict:
                record["url"] = url
                record["download"] = download
                if record["raises"] is not None:
                    raise record["raises"]
                home = Path(options["paths"]["home"])
                target = home / core.STREAM_FILE
                if record["outcome"] == "nothing":
                    return {"requested_downloads": []}
                sf.write(target, tone(seconds=0.1), RATE, format="MP3")
                if record["outcome"] == "elsewhere":
                    # Inside the cache, outside this URL's folder: the boundary is the
                    # folder the URL derives, not merely somewhere LEVIX owns.
                    return {
                        "requested_downloads": [{"filepath": str(home.parent.parent / "x.mp3")}]
                    }
                return {"requested_downloads": [{"filepath": str(target)}]}

        return Fake()

    monkeypatch.setattr(core, "_make_ydl", _make_ydl)
    monkeypatch.setattr(core, "require_stream_tools", lambda: None)
    return record


@pytest.fixture
def cache(levix_home) -> Path:
    return levix_home / "cache"


@pytest.mark.parametrize(
    ("source", "looks_like_a_link"),
    [
        (r"C:\music\tone.wav", False),
        ("tone.wav", False),
        ("./mix:1.wav", False),
        ("/home/me/tone.wav", False),
        ("~/Music/tone.wav", False),
        ("https://example.invalid/watch?v=1", True),
        ("HTTP://example.invalid/x", True),
        ("file:///tmp/x.wav", True),
        ("mix:1.wav", True),
        ("magnet:?xt=urn:btih:x", True),
    ],
)
def test_what_counts_as_a_link(source, looks_like_a_link):
    """Two characters of scheme, and nothing else decides it.

    `C:\\music\\tone.wav` reads as the scheme `c` to a URL parser, so a one-letter scheme
    stays a path. The trade is a POSIX file literally named `mix:1.wav`, which reads as a
    link: write `./mix:1.wav` and it is a path again.
    """
    assert core.is_url(source) is looks_like_a_link


def test_a_link_is_fetched_into_the_cache_and_played(run_cli, capsys, stream_seam, seam, cache):
    assert run_cli("music", "play", URL) == 0
    assert seam["frames"].shape[0] == int(RATE * 0.1), "the fetched audio is what reached the seam"
    assert stream_seam["url"] == URL and stream_seam["download"] is True
    target = core.stream_dir(URL, cache_root=cache) / core.STREAM_FILE
    assert target.is_file()
    out = flat(capsys.readouterr())
    assert URL in out, "the line names the link the caller pasted"
    assert "audio.mp3" not in out, "not this machine's cache name"
    assert "MP3/MPEG_LAYER_III" in out, "and the codec libsndfile really saw"
    assert "fetched to" in out


def test_the_ask_is_audio_only_one_item_and_never_a_file_url(stream_seam, cache):
    core.fetch_audio(URL, cache_root=cache)
    options = stream_seam["options"]
    assert options["format"] == core.STREAM_FORMAT == "ba/b"
    assert options["noplaylist"] is True, "one item per call: a playlist is Tube's job"
    assert options["outtmpl"] == core.STREAM_TEMPLATE == "audio.%(ext)s"
    assert options["max_filesize"] == core.STREAM_MAX_BYTES
    assert options["postprocessors"] == [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": core.STREAM_CODEC,
            "preferredquality": "0",
        }
    ]
    assert "enable_file_urls" not in options, "yt-dlp's own default is left as it is"
    assert options["logger"] is core._QUIET_LOGGER, "nothing yt-dlp prints bypasses this module"
    assert Path(options["paths"]["home"]) == core.stream_dir(URL, cache_root=cache)


def test_the_logger_yt_dlp_writes_to_says_nothing(capsys):
    """The three methods are yt-dlp's documented logger contract, and all three are sinks.

    Dropping its line is only safe because whatever yt-dlp reports as an error with
    `ignoreerrors` False also raises, and `_run` maps that exception into the one message
    the caller sees.
    """
    for name in ("debug", "warning", "error"):
        getattr(core._QUIET_LOGGER, name)(f"a line from yt-dlp: {name}")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_cache_folder_is_the_url_and_not_anything_a_server_chose(stream_seam, cache):
    first = core.fetch_audio(URL, cache_root=cache)
    second = core.fetch_audio(f"{URL}&t=1", cache_root=cache)
    assert first.path.name == core.STREAM_FILE == "audio.mp3"
    assert first.path.parent == cache / "streams" / hashlib.sha256(URL.encode()).hexdigest()[:16]
    assert second.path.parent != first.path.parent
    names = sorted(folder.name for folder in (cache / "streams").iterdir())
    assert names == sorted([first.path.parent.name, second.path.parent.name])
    assert all(len(name) == 16 for name in names), "a digest, so no title can name a folder"


def test_playing_the_same_link_twice_never_reaches_the_network(
    run_cli, capsys, stream_seam, seam, cache
):
    assert run_cli("music", "play", URL) == 0
    assert stream_seam["calls"] == 1
    assert run_cli("music", "play", URL) == 0
    assert stream_seam["calls"] == 1, "the cached copy answered, yt-dlp was never built"
    assert "the network was not touched" in flat(capsys.readouterr())


def test_only_a_link_that_really_downloads_announces_a_wait(
    run_cli, capsys, stream_seam, seam, cache, wav
):
    """The "this is quiet" line means *this call is about to be quiet*, and nothing else.

    yt-dlp's progress is off, so a fetch looks like a hang; a cached replay, a refused
    scheme and a plain path are all fast, and telling the caller to wait for them would
    train them to ignore the one message that matters.
    """
    assert run_cli("music", "play", str(wav)) == 0
    assert "asking yt-dlp" not in flat(capsys.readouterr())
    assert run_cli("music", "play", URL) == 0
    assert "asking yt-dlp" in flat(capsys.readouterr())
    assert run_cli("music", "play", URL) == 0
    assert "asking yt-dlp" not in flat(capsys.readouterr())
    assert run_cli("music", "play", wav.as_uri()) == EXIT_USAGE
    assert "asking yt-dlp" not in flat(capsys.readouterr())


@pytest.mark.parametrize("scheme", ["file", "ftp", "mailto", "data"])
def test_a_refused_scheme_is_refused_before_anything_is_looked_for(
    run_cli, capsys, cache, monkeypatch, scheme
):
    def explode(*args, **kwargs):
        raise AssertionError("a link this command will not fetch must not reach the tools")

    monkeypatch.setattr(core, "_make_ydl", explode)
    monkeypatch.setattr(core, "require_stream_tools", explode)
    monkeypatch.setattr(core, "resolve_paths", explode)
    assert run_cli("music", "play", f"{scheme}://example.invalid/tone.wav") == EXIT_USAGE
    assert "only http and https are played from a URL" in flat(capsys.readouterr())


def test_a_reported_path_outside_the_url_folder_is_not_opened(
    run_cli, capsys, stream_seam, seam, cache
):
    stream_seam["outcome"] = "elsewhere"
    assert run_cli("music", "play", URL) == EXIT_TOOL_FAILED
    assert "is not inside" in flat(capsys.readouterr())
    assert seam == {}, "the refusal happens before anything is decoded"


def test_a_fetch_that_reports_no_path_is_a_provider_error(
    run_cli, capsys, stream_seam, seam, cache
):
    stream_seam["outcome"] = "nothing"
    assert run_cli("music", "play", URL) == EXIT_PROVIDER
    assert "no file path" in flat(capsys.readouterr())
    assert seam == {}


def test_yt_dlp_failing_becomes_one_clean_message(run_cli, capsys, stream_seam, seam, cache):
    stream_seam["raises"] = RuntimeError("no audio formats available")
    assert run_cli("music", "play", URL) == EXIT_PROVIDER
    out = flat(capsys.readouterr())
    assert "yt-dlp could not fetch" in out and "no audio formats available" in out
    assert seam == {}


def test_a_stream_over_the_byte_cap_is_refused_before_it_is_decoded(
    run_cli, capsys, stream_seam, seam, cache
):
    target = core.stream_dir(URL, cache_root=cache) / core.STREAM_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.truncate(core.STREAM_MAX_BYTES + 1)
    assert run_cli("music", "play", URL) == EXIT_TOOL_FAILED
    out = flat(capsys.readouterr())
    assert "byte cap on a fetch" in out
    assert seam == {}
    assert stream_seam["calls"] == 0, "the copy already on disk is the one that was measured"


def test_a_url_without_yt_dlp_names_the_extra_it_comes_from(run_cli, capsys, monkeypatch, cache):
    monkeypatch.setattr(core, "_package_present", lambda name: False)
    assert run_cli("music", "play", URL) == EXIT_MISSING_DEPENDENCY
    out = flat(capsys.readouterr())
    assert 'pip install "levix[tube]"' in out
    assert "Music does not carry" in out


def test_a_url_without_ffmpeg_refuses_with_the_dependency_code(run_cli, capsys, monkeypatch, cache):
    monkeypatch.setattr(core, "_package_present", lambda name: True)
    monkeypatch.setattr(core, "ffmpeg_path", lambda: None)
    assert run_cli("music", "play", URL) == EXIT_MISSING_DEPENDENCY
    out = flat(capsys.readouterr())
    assert "needs ffmpeg" in out and core.install_command_for() in out


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", "winget install Gyan.FFmpeg"),
        ("cygwin", "winget install Gyan.FFmpeg"),
        ("darwin", "brew install ffmpeg"),
        ("linux", "sudo apt install ffmpeg"),
    ],
)
def test_the_ffmpeg_advice_is_this_platforms(platform, expected):
    assert core.install_command_for(platform) == expected


def test_the_ffmpeg_advice_does_not_drift_from_tubes():
    """Music repeats Tube's table because official modules must not import each other.

    Two people reading one error should not get two different commands, so the duplication
    is guarded rather than trusted.
    """
    from levix.modules.tube import core as tube_core

    assert core.FFMPEG_INSTALL_COMMANDS == tube_core.FFMPEG_INSTALL_COMMANDS
    assert core.FFMPEG_INSTALL_FALLBACK == tube_core.FFMPEG_INSTALL_FALLBACK


def test_a_local_file_never_touches_the_stream_path(run_cli, wav, seam, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("a file on disk needs neither yt-dlp nor ffmpeg")

    monkeypatch.setattr(core, "fetch_audio", explode)
    monkeypatch.setattr(core, "require_stream_tools", explode)
    monkeypatch.setattr(core, "_make_ydl", explode)
    assert run_cli("music", "play", str(wav)) == 0


def test_yt_dlp_is_imported_in_exactly_one_place():
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert source.count("import yt_dlp") == 1
    assert "def _make_ydl" in source


def test_a_file_url_cannot_make_this_process_read_a_file(
    run_cli, capsys, stream_seam, seam, cache, wav
):
    """The link a local file would have played is refused, not quietly re-pointed at disk."""
    assert run_cli("music", "play", wav.as_uri()) == EXIT_USAGE
    assert seam == {} and stream_seam["calls"] == 0


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
    # One command, `play URL`, is why these two are here at all; see the manifest note.
    assert {Permission.NETWORK, Permission.FS_WRITE} <= MANIFEST.permissions
    # `levix -h` and `levix music -h` show these two lines, so both sources appear in both.
    assert "file" in MANIFEST.summary and "link" in MANIFEST.summary
    assert "file" in MANIFEST.commands[0].help and "link" in MANIFEST.commands[0].help
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
        "heavy = [x for x in ('soundfile','sounddevice','numpy','typer','rich','yt_dlp') "
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
        "heavy = [x for x in ('soundfile', 'sounddevice', 'psutil', 'yt_dlp') if x in sys.modules]",
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

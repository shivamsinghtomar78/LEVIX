"""The Files module: the wall, the walk, the encoding chain, the overwrite rules.

Everything here runs against a real temporary directory. A file manager cannot be
tested against a mock filesystem, because the bugs that matter live in the operating
system: how `..` collapses, what order `os.walk` gives, whether a `C:\\root\\ab` string
prefix lets the sibling `C:\\root\\abc` through, what Windows does to a name.

The browser tests are `integration` because Textual needs a running event loop; they
drive the real widget through a `Pilot` and then assert on what the disk looks like.

Note on streams: `levix.main` renders every `LevixError` on stderr and the module's own
tables on stdout, so the assertions use `both()`, never one stream alone.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from levix.errors import EXIT_CANCELLED, EXIT_RUNTIME, EXIT_UNKNOWN_MODULE, EXIT_USAGE
from levix.module import Permission
from levix.modules.files import MANIFEST, core
from levix.modules.files.core import FilesError, RequestError, UnsafePathError

WIN = sys.platform.startswith("win")

FILES = {
    "a.txt": "one\ntwo\nthree\n",
    "notes.md": "# notes\n\nalpha 42\nbeta\n",
    "sub/b.py": "print('alpha')\n",
    "sub/deep/c.log": "alpha again\n",
    "out/keep": "",
}
#: Dot-prefixed, so it is hidden on every platform and must stay out of a default search.
HIDDEN_NAME = ".alpha-hidden.txt"
HIDDEN_TEXT = "alpha hidden\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _populate(root: Path) -> Path:
    for relative, text in FILES.items():
        _write(root / relative, text)
    _write(root / HIDDEN_NAME, HIDDEN_TEXT)
    (root / "blob.bin").write_bytes(b"\x00\x01\x02alpha\x00\x00")
    # "café" in cp1252: not valid utf-8, so the decode chain has to reach step two.
    (root / "legacy.txt").write_bytes(b"caf\xe9 was here\n")
    return root


@pytest.fixture
def tree(tmp_path) -> Path:
    return _populate(tmp_path / "project")


@pytest.fixture
def sandbox(tmp_path, monkeypatch) -> Path:
    """A tree plus a working directory inside it, i.e. how the CLI is really used."""
    root = _populate(tmp_path / "demo")
    monkeypatch.chdir(root)
    return root


def both(captured) -> str:
    return captured.out + captured.err


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    """Make a link, or skip: Windows needs developer mode/administration for this."""
    try:
        os.symlink(str(target), str(link), target_is_directory=directory)
    except (OSError, AttributeError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks on this account: {exc}")


def _blocked_open(monkeypatch, path: Path):
    """Make `path.open()` fail once, the only portable way to test the read-error paths."""
    real = Path.open

    def explode(self, mode="r", *args, **kwargs):
        if self == path and "b" in str(mode):
            raise OSError(13, "Permission denied")
        return real(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", explode)


# ----------------------------------------------------------------------------------
# Path geometry: the wall
# ----------------------------------------------------------------------------------


def test_is_within_accepts_the_directory_itself_and_its_children(tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    assert core.is_within(root, root)
    assert core.is_within(root / "a" / "b", root)


def test_is_within_compares_components_not_string_prefixes(tmp_path):
    """`C:\\root\\ab` is a prefix of `C:\\root\\abc`, which is exactly the bug avoided."""
    assert not core.is_within(tmp_path / "ab" / "x", tmp_path / "a")
    assert not core.is_within(Path("C:/root/abc/f.txt"), Path("C:/root/ab"))


def test_a_different_drive_is_never_inside_the_wall():
    assert not core.is_within(Path("D:/data/x.txt"), Path("C:/data"))


def test_a_unc_share_is_never_inside_a_local_root():
    remote = Path("//server/share/x.txt")
    assert not core.is_within(remote, Path("C:/root"))


@pytest.mark.skipif(not WIN, reason="only a case-insensitive filesystem folds case")
def test_windows_paths_are_matched_case_insensitively():
    assert core.is_within(Path("C:/ROOT/A/F.TXT"), Path("C:/root"))
    assert not core.is_within(Path("D:/ROOT/A/F.TXT"), Path("C:/root"))


def test_resolve_keeps_shell_semantics_for_relative_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "here.txt", "x")
    assert core.resolve("here.txt") == (tmp_path / "here.txt").resolve(strict=False)


def test_resolve_allows_a_detour_that_ends_back_inside(tmp_path):
    """The wall is decided on the resolved path, so a harmless `..` is not refused."""
    root = tmp_path / "root"
    (root / "in").mkdir(parents=True)
    _write(root / "in" / "f.txt", "x")
    wandering = root / "in" / ".." / "in" / "f.txt"
    assert core.resolve(wandering, root=root) == (root / "in" / "f.txt").resolve(strict=False)


def test_resolve_refuses_a_traversal_out_of_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = _write(tmp_path / "sensitive.txt", "do not touch")
    with pytest.raises(UnsafePathError) as caught:
        core.resolve(root / ".." / "sensitive.txt", root=root, label="deletion target")
    assert "outside the wall" in caught.value.message
    assert "deletion target" in caught.value.message
    assert caught.value.exit_code == EXIT_USAGE
    assert outside.exists(), "a refusal must not have touched anything"


def test_resolve_refuses_an_absolute_path_outside_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        core.resolve(tmp_path / "elsewhere" / "x.txt", root=root)


def test_resolve_refuses_a_sibling_that_shares_a_name_prefix(tmp_path):
    root = tmp_path / "ab"
    root.mkdir()
    with pytest.raises(UnsafePathError, match="outside the wall"):
        core.resolve(tmp_path / "abc" / "f.txt", root=root)


def test_resolve_needs_no_root_and_never_touches_the_disk(tmp_path):
    missing = tmp_path / "no" / "such" / "dir"
    assert core.resolve(missing) == missing.resolve(strict=False)


def test_a_missing_path_is_refused_by_require_exists(tmp_path):
    with pytest.raises(RequestError, match="does not exist"):
        core.require_exists(tmp_path / "ghost.txt")
    assert core.require_exists(tmp_path) == tmp_path


def test_a_broken_link_is_still_an_existing_entry(tmp_path):
    link = tmp_path / "dangling"
    _symlink(tmp_path / "nowhere", link)
    assert core.require_exists(link) == link


@pytest.mark.skipif(WIN, reason="POSIX symlinks need no privilege here")
def test_a_linked_directory_is_listed_but_never_walked_into(tmp_path):
    """Nothing in the module descends or deletes *through* a link, so a link out of the
    root cannot turn into an operation outside it."""
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _write(elsewhere / "far.txt", "x")
    _symlink(elsewhere, root / "data" / "escape", directory=True)

    found = [p.name for p, _ in core.walk_paths(root)]
    assert "escape" in found, "the link itself is reported"
    assert "far.txt" not in found, "and nothing beyond it is reached"

    plan = core.plan_delete([str(root / "data")], root=root, recursive=True)
    assert [item.path.name for item in plan.items] == ["escape", "data"]
    core.execute_delete(plan)
    assert (elsewhere / "far.txt").exists(), "the target survives a recursive delete"


# ----------------------------------------------------------------------------------
# Console-safe text (HARD RULE 3)
# ----------------------------------------------------------------------------------


def test_printable_escapes_control_characters_onto_one_line():
    assert core.printable("a\x07b") == "a\\x07b"
    assert core.printable("tab\there") == "tab\\x09here"


def test_printable_survives_a_name_the_console_cannot_encode(monkeypatch):
    """A bullet in a file name must not raise inside Rich's win32 writer."""

    class _WindowsConsole:
        encoding = "cp1252"

    monkeypatch.setattr(sys, "stdout", _WindowsConsole())
    text = core.printable("bad\u2603name\ttail")
    assert "\u2603" not in text, "cp1252 has no snowman, so it must come back escaped"
    assert text == "bad\\u2603name\\x09tail"
    assert text.encode("cp1252")


def test_printable_keeps_what_the_console_can_encode(monkeypatch):
    """cp1252 really does hold U+2022, so escaping it would be a needless lie about the name."""

    class _WindowsConsole:
        encoding = "cp1252"

    monkeypatch.setattr(sys, "stdout", _WindowsConsole())
    assert core.printable("bad\u2022name.txt") == "bad\u2022name.txt"


def test_printable_leaves_a_utf8_console_alone(monkeypatch):
    class _Utf8Console:
        encoding = "utf-8"

    monkeypatch.setattr(sys, "stdout", _Utf8Console())
    assert core.printable("bad\u2603name.txt") == "bad\u2603name.txt"


def test_printable_accepts_path_objects(tmp_path):
    assert core.printable(tmp_path) == core.printable(str(tmp_path))


# ----------------------------------------------------------------------------------
# Walking and name search
# ----------------------------------------------------------------------------------


def test_walk_reports_directories_and_files_in_a_stable_order(tree):
    def names_of() -> list[tuple[str, bool]]:
        return [
            (path.relative_to(tree).as_posix(), is_dir) for path, is_dir in core.walk_paths(tree)
        ]

    seen = names_of()
    assert ("a.txt", False) in seen
    assert ("sub", True) in seen
    assert seen == names_of(), "output must not depend on readdir order"
    # directories of a level first, then its files, each sorted case-insensitively
    root_level = [name for name, is_dir in seen if "/" not in name and is_dir]
    assert root_level == sorted(root_level, key=str.casefold)


def test_walk_hides_dot_files_unless_asked(tree):
    plain = [p.name for p, _ in core.walk_paths(tree)]
    assert HIDDEN_NAME not in plain
    assert HIDDEN_NAME in [p.name for p, _ in core.walk_paths(tree, include_hidden=True)]


def test_walk_depth_cut_is_measured_from_the_root(tree):
    """`max_depth` counts levels below the root, the way `find -maxdepth` does."""
    top = [p.relative_to(tree).as_posix() for p, _ in core.walk_paths(tree, max_depth=1)]
    assert "a.txt" in top and "sub" in top
    assert "sub/b.py" not in top, "depth 1 never enters a directory"

    one_level = [p.relative_to(tree).as_posix() for p, _ in core.walk_paths(tree, max_depth=2)]
    assert "sub/b.py" in one_level
    assert "sub/deep/c.log" not in one_level

    assert list(core.walk_paths(tree, max_depth=0)) == []


def test_walk_counts_hidden_entries_so_the_summary_can_say_what_it_skipped(tree):
    stats = core.ScanStats()
    files = [p for p, is_dir in core.walk_paths(tree, stats=stats) if not is_dir]
    assert stats.files_examined == len(files) == 7
    assert stats.skipped_hidden == 1
    assert stats.directories_visited == 4  # root, sub, sub/deep, out
    assert HIDDEN_NAME not in [p.name for p in files]


def test_extensions_are_normalised_from_every_way_a_user_types_them():
    assert core.normalize_extensions(["py", ".PY", "*.md", "txt,log", "", "a;b"]) == (
        ".py",
        ".md",
        ".txt",
        ".log",
        ".a",
        ".b",
    )


def test_search_by_substring_ignores_case_unless_told_not_to(tree):
    stats = core.ScanStats()
    hits = list(core.search_names(tree, "PY", stats=stats))
    assert [h.path.name for h in hits] == ["b.py"]
    assert stats.matches == 1 and stats.complete
    assert list(core.search_names(tree, "PY", ignore_case=False, stats=core.ScanStats())) == []


def test_search_by_glob_and_the_empty_pattern(tree):
    globs = list(core.search_names(tree, "*.txt", use_glob=True, stats=core.ScanStats()))
    assert sorted(h.path.name for h in globs) == ["a.txt", "legacy.txt"]
    everything = list(core.search_names(tree, "", stats=core.ScanStats()))
    assert len(everything) > len(globs), "an empty pattern matches every entry"


def test_search_reports_directories_and_labels_them(tree):
    hits = {h.path.name: h for h in core.search_names(tree, "", stats=core.ScanStats())}
    assert hits["sub"].kind == "dir"
    assert hits["a.txt"].kind == "file"
    assert hits["a.txt"].size_bytes == len(FILES["a.txt"])


def test_search_extension_filter(tree):
    names = [
        h.path.name for h in core.search_names(tree, "", extensions=["txt"], stats=core.ScanStats())
    ]
    assert sorted(names) == ["a.txt", "legacy.txt"], "the hidden dot-file is not searched"
    both_ext = [
        h.path.name
        for h in core.search_names(tree, "", extensions=["txt", "md"], stats=core.ScanStats())
    ]
    assert sorted(both_ext) == ["a.txt", "legacy.txt", "notes.md"]


def test_search_limit_stops_and_says_so(tree):
    stats = core.ScanStats()
    hits = list(core.search_names(tree, "", limit=2, stats=stats))
    assert len(hits) == 2
    assert not stats.complete
    assert "limit 2" in stats.stopped_early


def test_search_hidden_option_reaches_the_dot_file(tree):
    without = core.ScanStats()
    assert list(core.search_names(tree, "alpha-hidden", stats=without)) == []
    assert without.skipped_hidden >= 1
    with_hidden = core.ScanStats()
    found = list(core.search_names(tree, "alpha-hidden", include_hidden=True, stats=with_hidden))
    assert [h.path.name for h in found] == [HIDDEN_NAME]


def test_search_depth_option_holds_the_walk_at_the_line(tree):
    stats = core.ScanStats()
    top = list(core.search_names(tree, "c.log", max_depth=2, stats=stats))
    assert top == [], "c.log sits three levels under the root"
    deep = list(core.search_names(tree, "c.log", max_depth=3, stats=core.ScanStats()))
    assert [h.path.name for h in deep] == ["c.log"]


# ----------------------------------------------------------------------------------
# Content search
# ----------------------------------------------------------------------------------


def test_grep_finds_the_line_and_numbers_it(tree):
    stats = core.ScanStats()
    hits = list(core.search_contents(tree, "alpha", stats=stats))
    got = {(h.path.relative_to(tree).as_posix(), h.line_number) for h in hits}
    assert got == {("notes.md", 3), ("sub/b.py", 1), ("sub/deep/c.log", 1)}
    assert stats.matches == 3


def test_grep_respects_extension_and_depth(tree):
    stats = core.ScanStats()
    only_logs = list(core.search_contents(tree, "alpha", extensions=["log"], stats=stats))
    assert [h.path.name for h in only_logs] == ["c.log"]
    shallow = core.ScanStats()
    top_only = list(core.search_contents(tree, "alpha", max_depth=1, stats=shallow))
    assert {h.path.name for h in top_only} == {"notes.md"}


def test_grep_skips_binary_by_nul_sniffing_and_counts_it(tree):
    stats = core.ScanStats()
    hits = list(core.search_contents(tree, "alpha", stats=stats))
    assert "blob.bin" not in {h.path.name for h in hits}
    assert stats.skipped_binary == 1, "a skip is reported, never hidden"
    assert core.is_binary_head(b"ab\x00cd")
    assert not core.is_binary_head(b"ab\x01cd")
    assert not core.is_binary_head(b"caf\xe9\n")


def test_grep_skips_files_over_the_size_cap(tree):
    stats = core.ScanStats()
    list(core.search_contents(tree, "alpha", max_bytes=8, stats=stats))
    assert stats.skipped_too_large >= 1


def test_grep_size_cap_can_be_turned_off(tree):
    stats = core.ScanStats()
    hits = list(core.search_contents(tree, "alpha", max_bytes=0, stats=stats))
    assert stats.skipped_too_large == 0
    assert hits, "with no cap nothing is skipped for size"


@pytest.mark.skipif(WIN, reason="POSIX symlinks need no privilege here")
def test_grep_does_not_read_through_a_link(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = _write(tmp_path / "outside.txt", "alpha here\n")
    _symlink(outside, root / "link.txt")
    stats = core.ScanStats()
    assert list(core.search_contents(root, "alpha", stats=stats)) == []
    assert stats.skipped_symlink == 1


def test_grep_regex_and_case_options(tree):
    stats = core.ScanStats()
    numbers = list(core.search_contents(tree, r"\w+ [0-9]+", use_regex=True, stats=stats))
    assert [h.text for h in numbers] == ["alpha 42"]
    loose = core.ScanStats()
    assert len(list(core.search_contents(tree, "ALPHA", stats=loose))) == 3
    strict = core.ScanStats()
    assert list(core.search_contents(tree, "ALPHA", ignore_case=False, stats=strict)) == []


def test_grep_limit_marks_the_scan_incomplete(tree):
    stats = core.ScanStats()
    hits = list(core.search_contents(tree, "alpha", limit=1, stats=stats))
    assert len(hits) == 1
    assert not stats.complete
    assert "limit 1" in stats.stopped_early


def test_grep_unreadable_file_is_reported_not_fatal(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    _write(root / "good.txt", "alpha\n")
    bad = _write(root / "bad.txt", "alpha\n")
    _blocked_open(monkeypatch, bad)
    stats = core.ScanStats()
    hits = list(core.search_contents(root, "alpha", stats=stats))
    assert [h.path.name for h in hits] == ["good.txt"]
    assert stats.unreadable == 1
    assert any("bad.txt" in note for note in stats.errors)


# ----------------------------------------------------------------------------------
# Decoding and preview
# ----------------------------------------------------------------------------------


def test_decode_chain_prefers_utf8_then_cp1252_then_labels_latin1_lossy():
    assert core.decode_bytes("caf\u00e9".encode("utf-8")) == ("caf\u00e9", "utf-8")
    assert core.decode_bytes(b"caf\xe9") == ("caf\u00e9", "cp1252")
    text, encoding = core.decode_bytes(b"ab\x81cd")  # 0x81 is undefined in cp1252
    assert encoding == "latin-1 (lossy)"
    assert text == "ab\x81cd"


def test_preview_head_is_bounded_and_flags_more_lines(tree):
    result = core.preview(tree / "a.txt", lines=2)
    assert result.kind == "text" and result.encoding == "utf-8"
    assert result.lines == ("one", "two")
    assert result.truncated
    assert result.line_count == 3 and result.counted


def test_preview_zero_lines_uses_the_read_budget(tree):
    result = core.preview(tree / "a.txt", lines=0)
    assert result.lines == ("one", "two", "three")
    assert not result.truncated, "the file is far smaller than the 256 KiB budget"


def test_preview_falls_back_to_cp1252_and_says_which_it_used(tree):
    result = core.preview(tree / "legacy.txt", lines=5)
    assert result.encoding == "cp1252"
    assert "caf\u00e9" in result.lines[0]


def test_preview_of_a_latin1_only_file_admits_it_is_lossy(tmp_path):
    odd = tmp_path / "odd.txt"
    odd.write_bytes(b"line one \x81\nline two\n")
    result = core.preview(odd, lines=5)
    assert result.encoding == "latin-1 (lossy)"
    assert len(result.lines) == 2


def test_preview_of_binary_describes_instead_of_dumping(tmp_path):
    blob = tmp_path / "blob"
    blob.write_bytes(b"\x00\xff" * 40)
    result = core.preview(blob, lines=10)
    assert result.kind == "binary"
    assert result.lines == ()


def test_preview_of_a_directory_and_of_nothing_are_honest(tree, tmp_path):
    assert core.preview(tree / "sub").kind == "directory"
    missing = core.preview(tmp_path / "ghost")
    assert missing.entry.kind == "missing"
    assert missing.entry.exists is False
    assert missing.entry.modified_text == "-"


def test_preview_of_a_symlink_reports_the_link_not_the_target(tmp_path):
    target = _write(tmp_path / "target.txt", "x\n")
    link = tmp_path / "link.txt"
    _symlink(target, link)
    result = core.preview(link)
    assert result.kind == "symlink"
    assert result.entry.link_target == str(target)
    assert result.entry.size_bytes == os.lstat(link).st_size


def test_preview_unreadable_file_is_a_clean_files_error(tmp_path, monkeypatch):
    path = _write(tmp_path / "f.txt", "x\n")
    _blocked_open(monkeypatch, path)
    with pytest.raises(FilesError, match="cannot read"):
        core.preview(path)


@pytest.mark.parametrize(
    ("body", "expected"),
    [("a\nb\n", 2), ("a\nb", 2), ("", 0), ("\n", 1), ("a\n\n", 2)],
)
def test_count_lines_counts_the_last_unterminated_line(tmp_path, body, expected):
    path = tmp_path / "c.txt"
    path.write_text(body, encoding="utf-8", newline="\n")
    assert core.count_lines(path) == (expected, True)


def test_count_lines_refuses_to_read_a_huge_file(tmp_path):
    path = tmp_path / "big.txt"
    path.write_bytes(b"x\n" * 4)
    assert core.count_lines(path, max_bytes=2) == (None, False)
    assert core.preview(path, lines=5, count_line_total=True, count_max_bytes=2).counted is False
    assert (
        core.preview(path, lines=5, count_line_total=True, count_max_bytes=1 << 20).counted is True
    )


def test_line_count_can_be_skipped_entirely(tree):
    result = core.preview(tree / "a.txt", lines=1, count_line_total=False)
    assert result.counted is False and result.line_count is None


# ----------------------------------------------------------------------------------
# Metadata
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (999, "999 B"), (1024, "1.0 KiB"), (1536, "1.5 KiB"), (5 * 2**20, "5.0 MiB")],
)
def test_human_bytes_uses_binary_units(value, expected):
    assert core.human_bytes(value) == expected


def test_stat_entry_describes_a_directory_and_a_file(tree):
    folder = core.stat_entry(tree / "sub")
    assert folder.kind == "directory" and folder.is_dir
    file = core.stat_entry(tree / "a.txt")
    assert file.kind == "file" and file.size_bytes == len(FILES["a.txt"])
    assert len(file.modified_text) == len("2026-01-01 00:00:00")
    if WIN:
        assert file.created_text.endswith("(birth)")
    assert core.stat_entry(tree / "ghost").exists is False


def test_entries_in_only_answers_the_empty_question(tree, tmp_path):
    empty = tmp_path / "empty-dir"
    empty.mkdir()
    assert core.entries_in(empty) == []
    assert "keep" in core.entries_in(tree / "out")
    assert "b.py" in core.entries_in(tree / "sub")
    assert core.entries_in(tree / "a.txt") == [], "an unreadable thing is not a listing"


def test_is_hidden_covers_dot_names(tmp_path):
    assert core.is_hidden(tmp_path / ".x", ".x")
    assert not core.is_hidden(tmp_path / "x", "x")


# ----------------------------------------------------------------------------------
# Names a rename may not produce
# ----------------------------------------------------------------------------------


DANGEROUS = [
    ("", "empty"),
    ("   ", "whitespace"),
    (" pad", "whitespace"),
    ("pad ", "whitespace"),
    (".", "directory"),
    ("..", "directory"),
    ("...", "directory"),
    ("/etc/passwd", "separator"),
    ("sub/f.txt", "separator"),
    ("trailing.", "dot or a space"),
    ("trailing ", "whitespace"),
    ("x" * 300, "255 bytes"),
]
if WIN:
    DANGEROUS += [
        ("sub\\f.txt", "separator"),
        ("C:/somewhere/f.txt", "bare name"),
        ("\\\\server\\share\\f.txt", "bare name"),
        ("C:x", "drive"),
        ("nul", "reserved"),
        ("COM1.log", "reserved"),
        ("LPT9", "reserved"),
    ]


@pytest.mark.parametrize(("name", "fragment"), DANGEROUS)
def test_dangerous_names_are_refused_before_anything_moves(name, fragment):
    with pytest.raises(RequestError) as caught:
        core.validate_new_name(name)
    assert fragment.lower() in caught.value.message.lower(), caught.value.message


def test_a_plain_new_name_passes_through_unchanged():
    assert core.validate_new_name("report-2026.01.txt") == "report-2026.01.txt"


# ----------------------------------------------------------------------------------
# copy / move / rename
# ----------------------------------------------------------------------------------


def test_copy_into_a_directory_uses_that_directory(tree):
    result = core.copy_entry(tree / "a.txt", tree / "out", root=tree)
    assert result.verb == "copied"
    assert result.destination == (tree / "out" / "a.txt").resolve(strict=False)
    assert result.bytes_moved == len(FILES["a.txt"])
    assert (tree / "out" / "a.txt").read_text(encoding="utf-8") == FILES["a.txt"]
    assert (tree / "a.txt").exists(), "a copy leaves the source alone"


def test_copy_to_a_new_name(tree):
    result = core.copy_entry(tree / "a.txt", tree / "copy.txt", root=tree)
    assert result.destination.name == "copy.txt"
    assert (tree / "copy.txt").exists()


def test_copy_refuses_to_overwrite_without_force(tree):
    _write(tree / "out" / "a.txt", "different\n")
    with pytest.raises(RequestError) as caught:
        core.copy_entry(tree / "a.txt", tree / "out", root=tree)
    assert "already exists" in caught.value.message
    assert "--force" in caught.value.hint
    assert "confirm" in caught.value.hint
    assert (tree / "out" / "a.txt").read_text(encoding="utf-8") == "different\n"


def test_copy_with_force_replaces_the_target(tree):
    _write(tree / "out" / "a.txt", "different\n")
    result = core.copy_entry(tree / "a.txt", tree / "out", root=tree, force=True)
    assert result.forced is True
    assert (tree / "out" / "a.txt").read_text(encoding="utf-8") == FILES["a.txt"]


def test_copy_refuses_the_same_entry_on_both_sides(tree):
    with pytest.raises(RequestError, match="same entry"):
        core.copy_entry(tree / "a.txt", tree / "a.txt", root=tree)


def test_copy_refuses_to_put_a_directory_inside_itself(tree):
    with pytest.raises(RequestError, match="into itself"):
        core.copy_entry(tree / "sub", tree / "sub" / "deep", root=tree)


def test_copy_needs_a_real_source(tree):
    with pytest.raises(RequestError, match="does not exist"):
        core.copy_entry(tree / "ghost.txt", tree / "out", root=tree)


def test_copy_honours_the_wall_on_the_destination_only(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = _write(tmp_path / "outside.txt", "read me\n")
    # Reading from anywhere is what the user named; writing outside the wall is not.
    with pytest.raises(UnsafePathError, match="destination"):
        core.copy_entry(outside, tmp_path / "escape.txt", root=root)
    assert not (tmp_path / "escape.txt").exists()


def test_copy_of_a_tree_keeps_the_structure(tmp_path):
    src = tmp_path / "src"
    _write(src / "a" / "b.txt", "x\n")
    _write(src / "c.txt", "y\n")
    result = core.copy_entry(src, tmp_path / "dst")
    assert result.destination.is_dir()
    names = sorted(p.name for p in result.destination.rglob("*") if p.is_file())
    assert names == ["b.txt", "c.txt"]


def test_move_renames_and_leaves_nothing_behind(tree):
    result = core.move_entry(tree / "a.txt", tree / "out", root=tree)
    assert result.verb == "moved"
    assert not (tree / "a.txt").exists()
    assert (tree / "out" / "a.txt").read_text(encoding="utf-8") == FILES["a.txt"]


def test_move_refuses_silent_overwrite_then_honours_force(tree):
    _write(tree / "out" / "b.py", "old\n")
    with pytest.raises(RequestError, match="already exists"):
        core.move_entry(tree / "sub" / "b.py", tree / "out", root=tree)
    assert (tree / "sub" / "b.py").exists(), "a refusal moves nothing"
    core.move_entry(tree / "sub" / "b.py", tree / "out", root=tree, force=True)
    assert (tree / "out" / "b.py").read_text(encoding="utf-8") == FILES["sub/b.py"]
    assert not (tree / "sub" / "b.py").exists()


def test_move_refuses_into_itself(tree):
    with pytest.raises(RequestError, match="into itself"):
        core.move_entry(tree / "sub", tree / "sub" / "deep", root=tree)


def test_rename_stays_in_its_own_directory(tree):
    result = core.rename_entry(tree / "a.txt", "renamed.txt", root=tree)
    assert (tree / "renamed.txt").read_text(encoding="utf-8") == FILES["a.txt"]
    assert result.destination.parent == tree.resolve(strict=False)


def test_rename_with_a_separator_is_impossible(tree):
    with pytest.raises(RequestError, match="separator"):
        core.rename_entry(tree / "a.txt", "../escape.txt", root=tree)
    assert (tree / "a.txt").exists()
    with pytest.raises(RequestError):
        core.rename_entry(tree / "a.txt", "sub/other.txt", root=tree)
    assert (tree / "sub" / "other.txt").is_file() is False


def test_rename_default_wall_is_the_entrys_own_folder(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    entry = _write(root / "x.txt", "x")
    result = core.rename_entry(entry, "y.txt")
    assert result.destination == root / "y.txt"


def test_rename_refuses_an_existing_name_unless_forced(tree):
    with pytest.raises(RequestError, match="already exists"):
        core.rename_entry(tree / "a.txt", "notes.md", root=tree)
    assert (tree / "a.txt").exists()
    core.rename_entry(tree / "a.txt", "notes.md", root=tree, force=True)
    assert not (tree / "a.txt").exists()
    assert (tree / "notes.md").read_text(encoding="utf-8") == FILES["a.txt"]


def test_rename_to_the_same_name_is_refused(tree):
    with pytest.raises(RequestError, match="already has"):
        core.rename_entry(tree / "a.txt", "a.txt", root=tree)


# ----------------------------------------------------------------------------------
# delete: measure first, remove second
# ----------------------------------------------------------------------------------


def test_plan_of_a_single_file_measures_it(tree):
    plan = core.plan_delete([str(tree / "a.txt")], root=tree, recursive=False)
    assert plan.file_count == 1 and plan.dir_count == 0
    assert plan.total_bytes == len(FILES["a.txt"])
    assert not plan.has_tree
    assert "1 file(s) and 0 directory(ies)" in plan.describe()
    assert core.printable(plan.wall) in plan.describe()


def test_plan_refuses_a_non_empty_directory_without_recursive(tree):
    with pytest.raises(RequestError) as caught:
        core.plan_delete([str(tree / "sub")], root=tree, recursive=False)
    assert "2 entry(ies) inside" in caught.value.message
    assert "--recursive" in caught.value.hint
    assert (tree / "sub" / "b.py").exists()


def test_plan_refuses_a_missing_target(tree):
    with pytest.raises(RequestError, match="does not exist"):
        core.plan_delete([str(tree / "ghost")], root=tree, recursive=False)


def test_plan_refuses_every_target_before_removing_anything(tree):
    with pytest.raises(RequestError):
        core.plan_delete([str(tree / "a.txt"), str(tree / "ghost")], root=tree, recursive=False)
    assert (tree / "a.txt").exists(), "a refused batch removes nothing at all"


def test_recursive_plan_orders_children_before_their_directory(tree):
    plan = core.plan_delete([str(tree / "sub")], root=tree, recursive=True)
    paths = [item.path.relative_to(tree).as_posix() for item in plan.items]
    assert paths == ["sub/deep/c.log", "sub/deep", "sub/b.py", "sub"]
    assert plan.has_tree
    assert plan.dir_count == 2 and plan.file_count == 2
    assert plan.total_bytes == len(FILES["sub/b.py"]) + len(FILES["sub/deep/c.log"])


def test_plan_drops_a_target_already_covered_by_another(tree):
    plan = core.plan_delete(
        [str(tree / "sub"), str(tree / "sub" / "b.py")], root=tree, recursive=True
    )
    assert len(plan.roots) == 1 and plan.roots[0].name == "sub"
    assert len(plan.covered) == 1
    assert [item.path.name for item in plan.items].count("b.py") == 1


def test_delete_refuses_to_escape_the_wall(tree, tmp_path):
    outside = _write(tmp_path / "outside.txt", "x")
    with pytest.raises(UnsafePathError, match="deletion target"):
        core.plan_delete([str(tree / ".." / "outside.txt")], root=tree, recursive=False)
    assert outside.exists()
    with pytest.raises(UnsafePathError):
        core.plan_delete([str(outside)], root=tree, recursive=False)
    assert outside.exists()


def test_execute_delete_removes_files_then_the_directories_that_held_them(tree):
    plan = core.plan_delete([str(tree / "sub")], root=tree, recursive=True)
    removed, reclaimed, failures = core.execute_delete(plan)
    assert failures == []
    assert len(removed) == 4
    assert reclaimed == plan.total_bytes
    assert not (tree / "sub").exists()
    assert (tree / "a.txt").exists(), "the sibling is untouched"


def test_execute_delete_of_an_empty_directory_needs_no_recursive(tree):
    empty = tree / "empty-dir"
    empty.mkdir()
    plan = core.plan_delete([str(empty)], root=tree, recursive=False)
    removed, _reclaimed, failures = core.execute_delete(plan)
    assert failures == [] and len(removed) == 1
    assert not empty.exists()


def test_execute_delete_of_a_directory_with_entries_needs_recursive(tree):
    with pytest.raises(RequestError, match="with 1 entry"):
        core.plan_delete([str(tree / "out")], root=tree, recursive=False)
    assert (tree / "out").exists()


def test_execute_delete_reports_a_locked_entry_and_keeps_going(tree, monkeypatch):
    real = core.remove_entry

    def explode(item):
        if item.path.name == "b.py":
            raise OSError(13, "Permission denied")
        real(item)

    monkeypatch.setattr(core, "remove_entry", explode)
    plan = core.plan_delete([str(tree / "sub")], root=tree, recursive=True)
    removed, _reclaimed, failures = core.execute_delete(plan)
    # b.py could not go, so the directory holding it could not go either: both refusals
    # are reported, and everything else in the plan still is removed.
    assert len(failures) == 2
    assert "b.py" in failures[0]
    assert len(removed) == len(plan.items) - 2
    assert (tree / "sub" / "b.py").exists()
    assert not (tree / "sub" / "deep").exists()


@pytest.mark.skipif(WIN, reason="POSIX symlinks need no privilege here")
def test_deleting_a_link_removes_the_link_and_never_the_target(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = _write(tmp_path / "target.txt", "precious\n")
    link = root / "link.txt"
    _symlink(target, link)
    plan = core.plan_delete([str(link)], root=root, recursive=False)
    assert plan.total_bytes == 0, "a link carries no payload of its own"
    removed, reclaimed, failures = core.execute_delete(plan)
    assert failures == [] and len(removed) == 1 and reclaimed == 0
    assert not link.exists()
    assert target.read_text(encoding="utf-8") == "precious\n"


# ----------------------------------------------------------------------------------
# The manifest and lazy loading (HARD RULE 1, HARD RULE 2)
# ----------------------------------------------------------------------------------


def test_manifest_declares_the_packaged_contract():
    assert MANIFEST.name == "files"
    assert MANIFEST.title == "Files"
    assert MANIFEST.cli_path == "levix.modules.files.cli:build_app"
    assert MANIFEST.command_names() == (
        "browse",
        "search",
        "preview",
        "copy",
        "move",
        "rename",
        "delete",
    )
    assert MANIFEST.requirements == () and MANIFEST.extras == ()
    assert MANIFEST.ui is not None
    assert MANIFEST.ui.mode == "suspend"
    assert MANIFEST.ui.argv == ("files", "browse")
    assert MANIFEST.documentation == "docs/modules/FILES.md"
    assert MANIFEST.permissions == frozenset({Permission.FS_READ, Permission.FS_WRITE})


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


def test_importing_the_manifest_pulls_in_nothing_heavy(tmp_path):
    completed = _child(
        tmp_path,
        "import levix.modules.files as m",
        "heavy = [x for x in ('psutil', 'yt_dlp', 'sounddevice', 'textual', 'rich', 'typer', "
        "'httpx') if x in sys.modules]",
        "print(len(m.MANIFEST.commands), heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "7 []"


def test_module_help_does_not_import_the_heavy_optional_dependencies(tmp_path):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        "code = main(['files', '-h'])",
        "heavy = [x for x in ('psutil', 'yt_dlp', 'sounddevice') if x in sys.modules]",
        "print(code, 'textual' in sys.modules, heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 False []"


def test_browse_help_does_not_start_a_screen(tmp_path):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        "code = main(['files', 'browse', '-h'])",
        "print(code, 'textual' in sys.modules)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 False"


# ----------------------------------------------------------------------------------
# Command surface, through the real entry point
# ----------------------------------------------------------------------------------


def test_module_help_lists_every_command(run_cli, capsys):
    assert run_cli("files", "-h") == 0
    text = both(capsys.readouterr())
    for name in MANIFEST.command_names():
        assert name in text
    assert "Traceback" not in text


def test_search_prints_matches_count_and_elapsed(run_cli, capsys, sandbox):
    assert run_cli("files", "search", ".", "log") == 0
    text = both(capsys.readouterr())
    assert "1 match(es)" in text
    assert "c.log" in text
    assert "directory(ies) walked" in text
    assert "Traceback" not in text


def test_search_with_grep_reports_the_skips_it_made(run_cli, capsys, sandbox):
    assert run_cli("files", "search", ".", "--grep", "alpha", "--max-bytes", "12") == 0
    text = both(capsys.readouterr())
    assert "skipped:" in text
    assert "over the size cap" in text
    assert "binary (NUL in head)" in text
    assert HIDDEN_NAME not in text


def test_max_bytes_zero_means_no_cap(run_cli, capsys, sandbox):
    """`--max-bytes` advertises "0 = no cap", so a file above the packaged default
    must still be searched at 0 and still be skipped at the default."""
    big = sandbox / "big.txt"
    big.write_text(
        "x" * core.DEFAULT_GREP_MAX_BYTES + "\nalpha at the end\n",
        encoding="utf-8",
        newline="\n",
    )
    assert big.stat().st_size > core.DEFAULT_GREP_MAX_BYTES

    assert run_cli("files", "search", ".", "--grep", "alpha at", "--max-bytes", "0") == 0
    text = both(capsys.readouterr())
    assert "big.txt" in text
    assert "over the size cap" not in text

    assert run_cli("files", "search", ".", "--grep", "alpha at") == 0
    text = both(capsys.readouterr())
    assert "big.txt" not in text
    assert "over the size cap" in text


def test_search_hidden_flag_reaches_the_dot_file(run_cli, capsys, sandbox):
    assert run_cli("files", "search", ".", "--include-hidden", "--grep", "alpha") == 0
    assert HIDDEN_NAME in both(capsys.readouterr())


def test_search_limit_reports_an_early_stop(run_cli, capsys, sandbox):
    assert run_cli("files", "search", ".", "--limit", "2") == 0
    text = both(capsys.readouterr())
    assert "2 match(es)" in text
    assert "stopped early" in text


def test_search_grep_regex_is_passed_through(run_cli, capsys, sandbox):
    assert run_cli("files", "search", ".", "--grep", r"alpha \d+", "--grep-regex") == 0
    assert "alpha 42" in both(capsys.readouterr())


def test_search_of_a_file_is_a_usage_error(run_cli, capsys, sandbox):
    assert run_cli("files", "search", "a.txt") == EXIT_USAGE
    text = both(capsys.readouterr())
    assert "needs a directory" in text
    assert "Traceback" not in text


def test_preview_shows_the_head_and_the_metadata(run_cli, capsys, sandbox):
    assert run_cli("files", "preview", "a.txt", "-n", "2") == 0
    text = both(capsys.readouterr())
    assert "one" in text and "two" in text and "three" not in text
    assert "head only" in text
    assert "modified" in text and "permissions" in text


def test_preview_names_the_encoding_it_used(run_cli, capsys, sandbox):
    assert run_cli("files", "preview", "legacy.txt") == 0
    assert "cp1252" in both(capsys.readouterr())


def test_preview_of_a_binary_says_so(run_cli, capsys, sandbox):
    assert run_cli("files", "preview", "blob.bin") == 0
    text = both(capsys.readouterr())
    assert "binary" in text
    assert "no text shown" in text


def test_preview_of_a_missing_file_exits_two(run_cli, capsys, sandbox):
    assert run_cli("files", "preview", "ghost.txt") == EXIT_USAGE
    assert "does not exist" in both(capsys.readouterr())


def test_preview_survives_a_name_the_console_cannot_encode(run_cli, capsys, sandbox):
    weird = _write(sandbox / "bad\u2022name.txt", "content\n")
    assert run_cli("files", "preview", weird.name) == 0
    assert "UnicodeEncodeError" not in both(capsys.readouterr())


def test_copy_then_rename_then_move_work_from_inside_the_tree(run_cli, capsys, sandbox):
    assert run_cli("files", "copy", "a.txt", "out") == 0
    assert (sandbox / "out" / "a.txt").exists()
    assert run_cli("files", "rename", "out/a.txt", "moved.txt") == 0
    assert (sandbox / "out" / "moved.txt").exists()
    assert run_cli("files", "move", "out/moved.txt", ".") == 0
    assert (sandbox / "moved.txt").exists()
    assert "Traceback" not in both(capsys.readouterr())


def test_copy_refuses_overwrite_without_force(run_cli, capsys, sandbox):
    assert run_cli("files", "copy", "a.txt", "notes.md") == EXIT_USAGE
    text = both(capsys.readouterr())
    assert "already exists" in text and "--force" in text


def test_copy_with_force_still_needs_a_terminal(run_cli, capsys, sandbox):
    """--force overrides the refusal, never the confirmation (HARD RULE 7)."""
    assert run_cli("files", "copy", "--force", "a.txt", "notes.md") == EXIT_CANCELLED
    assert "refusing to overwrite" in both(capsys.readouterr())
    assert (sandbox / "notes.md").read_text(encoding="utf-8") == FILES["notes.md"]


def test_copy_destination_outside_the_named_root_is_refused(run_cli, capsys, sandbox, tmp_path):
    assert run_cli("files", "copy", "--root", ".", "a.txt", "escape.txt") == 0
    assert (sandbox / "escape.txt").exists()
    assert run_cli("files", "copy", "--root", ".", "a.txt", str(tmp_path / "gone.txt")) == (
        EXIT_USAGE
    )
    assert "outside the wall" in both(capsys.readouterr())
    assert not (tmp_path / "gone.txt").exists()


def test_rename_cannot_be_used_to_move_outside(run_cli, capsys, sandbox, tmp_path):
    assert run_cli("files", "rename", "a.txt", "../escaped.txt") == EXIT_USAGE
    assert "separator" in both(capsys.readouterr())
    assert not (tmp_path / "escaped.txt").exists()
    assert (sandbox / "a.txt").exists()


def test_delete_refuses_without_a_terminal_and_removes_nothing(run_cli, capsys, sandbox):
    """Acceptance: exit 6, one clean message, no traceback, file untouched."""
    assert run_cli("files", "delete", "a.txt") == EXIT_CANCELLED
    captured = capsys.readouterr()
    assert "refusing to delete without a terminal" in both(captured)
    assert "Traceback" not in both(captured)
    assert (sandbox / "a.txt").exists()


def test_delete_yes_cannot_authorize_a_deletion(run_cli, capsys, sandbox):
    assert run_cli("files", "delete", "--yes", "a.txt") == EXIT_CANCELLED
    text = both(capsys.readouterr())
    assert "--yes cannot authorize" in text
    assert (sandbox / "a.txt").exists()


def test_delete_prints_the_plan_it_is_about_to_run(run_cli, capsys, sandbox):
    assert run_cli("files", "delete", "--recursive", "sub") == EXIT_CANCELLED
    # Rich wraps prose to the console width, so compare on one flattened line.
    flat = " ".join(capsys.readouterr().out.split())
    assert "about to delete" in flat
    assert "2 file(s) and 2 directory(ies)" in flat
    assert "c.log" in flat
    assert str(sandbox / "out") not in flat
    assert (sandbox / "sub" / "b.py").exists()


def test_delete_refuses_a_tree_without_recursive(run_cli, capsys, sandbox):
    assert run_cli("files", "delete", "sub") == EXIT_USAGE
    assert "--recursive" in both(capsys.readouterr())
    assert (sandbox / "sub").exists()


def test_delete_refuses_a_sibling_that_only_shares_a_prefix(run_cli, capsys, tmp_path, sandbox):
    """`demo2.txt` is not inside `demo`, even though the two strings share a prefix."""
    sibling = _write(tmp_path / "demo2.txt", "mine\n")
    assert run_cli("files", "delete", str(sibling)) == EXIT_USAGE
    assert "outside the wall" in both(capsys.readouterr())
    assert sibling.exists()


def test_delete_above_the_named_root_is_refused(run_cli, capsys, sandbox):
    outside = _write(sandbox.parent / "outside.txt", "x")
    assert run_cli("files", "delete", "../outside.txt") == EXIT_USAGE
    assert outside.exists()


def test_browse_refuses_a_piped_stdout_cleanly(run_cli, capsys, sandbox):
    assert run_cli("files", "browse") == EXIT_RUNTIME
    text = both(capsys.readouterr())
    assert "needs a real terminal" in text
    assert "Traceback" not in text


def test_browse_refuses_a_file_as_its_root(run_cli, capsys, sandbox):
    assert run_cli("files", "browse", "a.txt") == EXIT_USAGE
    assert "needs a directory" in both(capsys.readouterr())


def test_unknown_command_is_a_reported_error_not_a_crash(run_cli, capsys):
    """`errors.py` reserves EXIT_UNKNOWN_MODULE for a name nothing answers to."""
    assert run_cli("files", "frobnicate") == EXIT_UNKNOWN_MODULE
    captured = both(capsys.readouterr())
    assert "unknown command: frobnicate" in captured
    assert "Traceback" not in captured


# ----------------------------------------------------------------------------------
# The browser screen (integration: Textual needs an event loop)
# ----------------------------------------------------------------------------------


async def _settle(pilot, times: int = 6) -> None:
    """Let the tree's background directory loader catch up."""
    for _ in range(times):
        await pilot.pause()


async def _reach(pilot, app, name: str) -> Path:
    """Move the tree cursor onto `name`; the cursor starts on the root line itself."""
    app.query_one("#tree").cursor_line = 0
    await _settle(pilot, 2)
    for _ in range(25):
        node = app.query_one("#tree").cursor_node
        if node is not None and node.data.path.name == name:
            return node.data.path
        await pilot.press("down")
        await pilot.pause()
    raise AssertionError(f"never reached {name}")


def _drive(app, steps) -> None:
    """Run one Textual scenario in a fresh loop; `run_test` re-raises app errors."""

    async def main() -> None:
        async with app.run_test(headless=True, size=(120, 30)) as pilot:
            await steps(app, pilot)

    asyncio.run(main())


@pytest.mark.integration
def test_browse_screen_copies_previews_and_deletes(tmp_path):
    from textual.widgets import Input, Static

    from levix.modules.files.browse import BrowseApp, ConfirmScreen, HelpScreen, PromptScreen

    root = _populate(tmp_path / "shown")

    class Watched(BrowseApp):
        def __init__(self, base: Path) -> None:
            super().__init__(base)
            self.shown: list[str] = []

        def notify(self, message: str, **kwargs) -> None:
            self.shown.append(message)
            super().notify(message, **kwargs)

    app = Watched(root)

    async def go(app, pilot):
        def details() -> str:
            return str(app.query_one("#details", Static).content)

        await _settle(pilot)
        assert app.query_one("#tree").root.children, "the tree must actually mount"
        assert "root" in details()

        found = await _reach(pilot, app, "a.txt")
        assert found.parent.resolve(strict=False) == root.resolve(strict=False)
        await pilot.press("p")
        await pilot.pause()
        assert "one" in details(), "preview shows the head"

        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        app.screen.query_one(Input).value = "out"
        await pilot.press("enter")
        await _settle(pilot)
        assert (root / "out" / "a.txt").exists(), "copy landed inside the root"

        await _reach(pilot, app, "a.txt")
        await pilot.press("c")
        await pilot.pause()
        app.screen.query_one(Input).value = "../escaped.txt"
        await pilot.press("enter")
        await _settle(pilot)
        assert not (tmp_path / "escaped.txt").exists(), "the wall held"
        assert any("outside the wall" in note for note in app.shown)

        await _reach(pilot, app, "a.txt")
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        app.screen.query_one(Input).value = "yes"
        await pilot.press("enter")
        await _settle(pilot)
        assert (root / "a.txt").exists(), "the wrong word aborts"

        await _reach(pilot, app, "a.txt")
        await pilot.press("d")
        await pilot.pause()
        app.screen.query_one(Input).value = "DELETE"
        await pilot.press("enter")
        await _settle(pilot)
        assert not (root / "a.txt").exists(), "the right word deletes"
        assert (root / "out" / "a.txt").exists(), "and only the selected entry went"

        await pilot.press("q")
        await pilot.pause()

    _drive(app, go)
    assert app._exception is None
    assert any("copied" in note for note in app.shown)
    assert any("deleted 1 entry" in note for note in app.shown)
    assert any("cancelled" in note for note in app.shown)


@pytest.mark.integration
def test_browse_screen_refuses_a_directory_delete_and_points_at_the_cli(tmp_path):
    from levix.modules.files.browse import BrowseApp, ConfirmScreen

    root = tmp_path / "shown"
    (root / "folder" / "inner").mkdir(parents=True)
    _write(root / "folder" / "inner" / "x.txt", "x")
    shown: list[str] = []

    class Watched(BrowseApp):
        def notify(self, message: str, **kwargs) -> None:
            shown.append(message)
            super().notify(message, **kwargs)

    app = Watched(root)

    async def go(app, pilot):
        await _settle(pilot)
        await _reach(pilot, app, "folder")
        await pilot.press("d")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen), "nothing to confirm yet"
        await pilot.press("q")
        await pilot.pause()

    _drive(app, go)
    assert (root / "folder" / "inner" / "x.txt").exists(), "a refusal removes nothing"
    assert any("--recursive" in note for note in shown)


@pytest.mark.integration
def test_browse_open_expands_a_directory_and_previews_a_file(tmp_path):
    from textual.widgets import Static

    from levix.modules.files.browse import BrowseApp

    root = tmp_path / "shown"
    (root / "folder").mkdir(parents=True)
    _write(root / "folder" / "x.txt", "inside\n")
    app = BrowseApp(root)

    async def go(app, pilot):
        def details() -> str:
            return str(app.query_one("#details", Static).content)

        await _settle(pilot)
        await _reach(pilot, app, "folder")
        await pilot.press("enter")
        await _settle(pilot)
        folder = next(
            node for node in app.query_one("#tree").root.children if node.data.path.name == "folder"
        )
        assert folder.is_expanded, "enter expands"
        assert [node.data.path.name for node in folder.children] == ["x.txt"]

        await _reach(pilot, app, "x.txt")
        await pilot.press("o")
        await pilot.pause()
        assert "inside" in details(), "open on a file previews it"

        await pilot.press("r")
        await pilot.pause()
        assert app.query_one("#tree").root.children, "reload keeps a usable tree"

        await pilot.press("q")
        await pilot.pause()

    _drive(app, go)
    assert app._exception is None

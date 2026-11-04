"""Filesystem rules for the Files module: everything that touches the disk.

Rendering lives in `cli.py` and `browse.py`; this module only returns plain data, so
every rule - the traversal wall, the overwrite refusal, binary sniffing, the encoding
fallback chain - is unit-testable without a console, a terminal or a monkeypatch.

Two invariants the whole module is built around:

* **A named root is a wall.** Any path whose *resolved* form escapes the root the user
  named is refused (`UnsafePathError`). We compare resolved `Path` objects with
  `relative_to`, never string prefixes: `C:\\root\\abc` starts with `C:\\root\\ab` but is
  not inside it, and `relative_to` also gets Windows drive letters, UNC shares and
  case-insensitivity right, because pathlib compares Windows paths that way.
  Relative arguments keep shell semantics: they resolve against the current directory.
  The wall only decides what is allowed, never where a name is looked up.
* **Nothing destructive happens here.** The caller must pass `levix.approve` first;
  this module refuses a directory tree without `--recursive` and refuses silent
  overwrites.

Symlinks are never followed *into* a descent or a delete: a link is removed as a link,
which is the only interpretation that cannot destroy data somewhere else.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import stat
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from ...errors import EXIT_USAGE, LevixError

#: Bytes we look at before deciding a file is binary (a NUL byte means binary).
SNIFF_BYTES = 8192
#: How much of a file `preview` reads for the head, so a huge log costs 256 KiB.
HEAD_BUDGET = 256 * 1024
#: Files above this size are skipped by `--grep`: content search is for source trees.
DEFAULT_GREP_MAX_BYTES = 2 * 1024 * 1024
#: `preview` counts lines only for files up to this size; larger ones say "not counted".
LINE_COUNT_MAX_BYTES = 8 * 1024 * 1024
#: Decoding order. `latin-1` cannot fail, so it is last and always flagged as lossy.
ENCODING_CHAIN = ("utf-8", "cp1252")
HIDDEN_ATTR = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
_SEPARATORS = tuple(ch for ch in ("/", "\\", os.sep, os.altsep or "") if ch)
#: Windows device names: creating `nul.txt` leaves an entry that cannot be opened or
#: deleted later, so a rename asking for one is refused before it is attempted.
_RESERVED_WIN = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{digit}" for digit in range(1, 10)),
        *(f"lpt{digit}" for digit in range(1, 10)),
    }
)


class FilesError(LevixError):
    """A real failure on the way to the filesystem: exit 1, one clean message."""


class UnsafePathError(LevixError):
    """The request leaves (or would damage) somewhere outside the directory the user named."""

    exit_code = EXIT_USAGE


class RequestError(LevixError):
    """Bad argument for this command: missing path, name conflict, no --recursive."""

    exit_code = EXIT_USAGE


# ---------------------------------------------------------------------------
# paths: resolution, the wall, and console-safe text


def to_path(raw: str | os.PathLike[str]) -> Path:
    """A `Path` from user text, with `~` expanded. Never touches the filesystem."""
    return Path(os.fspath(raw)).expanduser()


def is_within(candidate: Path, parent: Path) -> bool:
    """True when `candidate` is `parent` or lives under it, decided by path geometry.

    `relative_to` compares *components*, so it does not fall for the string-prefix bug,
    and on Windows it is case- and separator-insensitive while keeping `C:` and `D:`
    apart and treating `\\\\server\\share` as a single root.
    """
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve(raw: str | os.PathLike[str], *, root: Path | None = None, label: str = "path") -> Path:
    """Resolve `raw` (against the current directory) and enforce the wall.

    `Path.resolve()` collapses `..` and follows symlinks, so the comparison is made on
    the real location rather than on what the user happened to type.
    """
    wall = None if root is None else root.resolve(strict=False)
    candidate = to_path(raw)
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:  # pragma: no cover - unreachable drives, IO errors
        raise FilesError(f"cannot resolve {printable(candidate)}: {exc.strerror or exc}") from exc
    if wall is not None and not is_within(resolved, wall):
        raise UnsafePathError(
            f"{label} {printable(resolved)} is outside the wall {printable(wall)}",
            hint=f"run this from inside {printable(wall)}, or widen it with --root DIR",
        )
    return resolved


def require_exists(path: Path, *, label: str = "path") -> Path:
    """Refuse a path that is neither a real entry nor a (possibly broken) link."""
    if not os.path.lexists(path):
        raise RequestError(f"{label} does not exist: {printable(path)}")
    return path


def printable(value: object) -> str:
    """`value` as text this console can actually encode.

    A Windows console is usually cp1252. Handing Rich a file name containing U+2022
    raises UnicodeEncodeError inside its win32 writer - a crash while printing
    somebody's file name, which is the worst possible place for one. Unencodable
    characters come back as `\\uXXXX` escapes and control characters as `\\xNN`, so the
    name stays readable and on one line.
    """
    text = os.fspath(value) if isinstance(value, os.PathLike) else str(value)
    text = "".join(
        char if (char.isprintable() and char != "\x7f") else f"\\x{ord(char):02x}" for char in text
    )
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    return text


# ---------------------------------------------------------------------------
# metadata


def human_bytes(value: float) -> str:
    """Binary units, the way operating systems report capacity."""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024.0 or unit == "PiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"  # pragma: no cover - the loop always returns first


def format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


@dataclass(frozen=True, slots=True)
class EntryStat:
    """What the OS says about one entry, with unknowns left unknown.

    `size_bytes` is `lstat` size, so a symlink reports the length of the link record,
    not the size of its target - printing the target's size here would be a lie.
    """

    path: Path
    exists: bool
    is_dir: bool
    is_file: bool
    is_symlink: bool
    link_target: str
    size_bytes: int
    mode: str
    modified: float
    accessed: float
    created: float
    created_is_birth: bool

    @property
    def kind(self) -> str:
        if not self.exists:
            return "missing"
        if self.is_symlink:
            return "symlink"
        return "directory" if self.is_dir else "file"

    @property
    def modified_text(self) -> str:
        return format_time(self.modified) if self.exists else "-"

    @property
    def accessed_text(self) -> str:
        return format_time(self.accessed) if self.exists else "-"

    @property
    def created_text(self) -> str:
        if not self.exists:
            return "-"
        return format_time(self.created) + (" (birth)" if self.created_is_birth else " (ctime)")


def stat_entry(path: Path) -> EntryStat:
    """`lstat` (never follow a link); an unreadable entry becomes an honest `exists=False`."""
    try:
        info = os.lstat(path)
    except OSError:
        return EntryStat(
            path=path,
            exists=False,
            is_dir=False,
            is_file=False,
            is_symlink=False,
            link_target="",
            size_bytes=0,
            mode="-",
            modified=0.0,
            accessed=0.0,
            created=0.0,
            created_is_birth=False,
        )
    mode = info.st_mode
    is_link = stat.S_ISLNK(mode)
    target = ""
    if is_link:
        with suppress(OSError):
            target = os.readlink(path)
    birth = getattr(info, "st_birthtime", None)
    return EntryStat(
        path=path,
        exists=True,
        is_dir=stat.S_ISDIR(mode),
        is_file=stat.S_ISREG(mode),
        is_symlink=is_link,
        link_target=target,
        size_bytes=int(info.st_size),
        mode=stat.filemode(mode),
        modified=info.st_mtime,
        accessed=info.st_atime,
        created=birth if birth is not None else info.st_ctime,
        created_is_birth=birth is not None or sys.platform.startswith("win"),
    )


def is_hidden(path: Path, name: str) -> bool:
    """Dot-files anywhere, plus the Windows hidden attribute when it is set."""
    if name.startswith("."):
        return True
    if not HIDDEN_ATTR:
        return False
    try:
        return bool(os.lstat(path).st_file_attributes & HIDDEN_ATTR)
    except (OSError, AttributeError):
        return False


def file_size(path: Path) -> int:
    """Size of the entry itself; a link counts as 0 because deleting it frees no payload."""
    if os.path.islink(path):
        return 0
    with suppress(OSError):
        return int(os.lstat(path).st_size)
    return 0


def entries_in(path: Path) -> list[str]:
    """Names inside a directory, for the empty/non-empty decision. `[]` when unreadable."""
    with suppress(OSError):
        return sorted(os.listdir(path))
    return []


def validate_new_name(new_name: str) -> str:
    """A bare, legal file name - the reason `rename` cannot be used to move or escape.

    Rejects empty, `.`, `..`, surrounding whitespace, anything with a separator or a
    drive/UNC prefix, trailing dots or spaces (Windows silently drops them, which would
    leave the user with a different name than they asked for), reserved device names and
    names too long for the filesystem.
    """
    if not new_name:
        raise RequestError("a new name cannot be empty")
    if new_name != new_name.strip():
        raise RequestError("a new name cannot start or end with whitespace")
    name = new_name
    if name in {os.curdir, os.pardir} or all(char == "." for char in name):
        raise RequestError(
            f"cannot rename to {printable(name)!r}: it names a directory, not an entry"
        )
    if any(sep in name for sep in _SEPARATORS):
        raise RequestError("a new name must be a bare name - no path separators (use `move`)")
    if os.path.splitdrive(name)[0]:
        raise RequestError("a new name cannot contain a drive letter or UNC prefix")
    if name.endswith((".", " ")):
        raise RequestError("a new name cannot end in a dot or a space (Windows drops them)")
    stem = name.split(".")[0].casefold()
    if sys.platform.startswith("win") and stem in _RESERVED_WIN:
        raise RequestError(f"{printable(name)!r} is a reserved Windows device name")
    if len(name.encode("utf-8", errors="replace")) > 255:
        raise RequestError("a new name longer than 255 bytes will not fit on most filesystems")
    return name


# ---------------------------------------------------------------------------
# walking and searching


@dataclass(slots=True)
class ScanStats:
    """Counters shared by the CLI and the tests while a search streams.

    A search that stopped early (limit reached or Ctrl+C) must say so: reporting
    "3 matches" while 900 files were silently ignored would be a lie.
    """

    files_examined: int = 0
    directories_visited: int = 0
    matches: int = 0
    skipped_hidden: int = 0
    skipped_binary: int = 0
    skipped_too_large: int = 0
    skipped_symlink: int = 0
    unreadable: int = 0
    stopped_early: str = ""
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.stopped_early


def walk_paths(
    root: Path,
    *,
    include_hidden: bool = False,
    max_depth: int | None = None,
    stats: ScanStats | None = None,
) -> Iterator[tuple[Path, bool]]:
    """Yield `(path, is_directory)`, directory by directory, sorted for stable output.

    `os.walk(..., followlinks=False)` is the deliberate choice: a symlinked directory is
    listed but never descended into, so a link cycle cannot hang the search or walk the
    whole disk through one `desktop.ini`-shaped trap.

    `max_depth` counts *levels below ROOT*: 1 reports the entries directly inside ROOT
    and nothing deeper, `None` reports everything. The cut applies to files and
    directories alike, so a listing can never contain a directory it refused to enter.
    """
    base_depth = len(root.parts)

    def _note(error: OSError) -> None:
        if stats is not None:
            stats.unreadable += 1
            stats.errors.append(printable(f"{error.filename}: {error.strerror or error}"))

    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False, onerror=_note):
        current = Path(dirpath)
        depth = len(current.parts) - base_depth
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []
            continue
        if stats is not None:
            stats.directories_visited += 1
        kept: list[str] = []
        for name in dirnames:
            if not include_hidden and is_hidden(current / name, name):
                if stats is not None:
                    stats.skipped_hidden += 1
                continue
            kept.append(name)
        dirnames[:] = sorted(kept, key=lambda text: text.casefold())
        for name in dirnames:
            yield current / name, True
        for name in sorted(filenames, key=lambda text: text.casefold()):
            if not include_hidden and is_hidden(current / name, name):
                if stats is not None:
                    stats.skipped_hidden += 1
                continue
            if stats is not None:
                stats.files_examined += 1
            yield current / name, False


def normalize_extensions(raw: Sequence[str]) -> tuple[str, ...]:
    """`py`, `.py`, `*.py` and `py,md` all become dotted lowercase forms."""
    out: list[str] = []
    for chunk in raw:
        for piece in chunk.replace(";", ",").split(","):
            text = piece.strip().lstrip("*").lower()
            if not text:
                continue
            if not text.startswith("."):
                text = f".{text}"
            if text not in out:
                out.append(text)
    return tuple(out)


def name_matches(name: str, pattern: str, *, use_glob: bool, ignore_case: bool) -> bool:
    """Empty pattern matches everything; otherwise a glob (`--glob`) or a substring."""
    if not pattern:
        return True
    if use_glob:
        return (
            fnmatch.fnmatchcase(name.casefold(), pattern.casefold())
            if ignore_case
            else fnmatch.fnmatchcase(name, pattern)
        )
    return pattern.casefold() in name.casefold() if ignore_case else pattern in name


@dataclass(frozen=True, slots=True)
class NameHit:
    path: Path
    is_dir: bool
    is_symlink: bool
    size_bytes: int

    @property
    def kind(self) -> str:
        return "dir" if self.is_dir else ("link" if self.is_symlink else "file")


@dataclass(frozen=True, slots=True)
class ContentHit:
    path: Path
    line_number: int
    text: str


# One name for "whatever a search yielded", so a caller that picks between the two
# generators in an if/else keeps a single iterator type instead of a join of two.
Hit = ContentHit | NameHit


def search_names(
    root: Path,
    pattern: str = "",
    *,
    use_glob: bool = False,
    ignore_case: bool = True,
    include_hidden: bool = False,
    extensions: Sequence[str] = (),
    max_depth: int | None = None,
    limit: int | None = None,
    stats: ScanStats | None = None,
) -> Iterator[Hit]:
    """Recursive name search. Directories are reported too - an empty tree says so."""
    exts = normalize_extensions(extensions)
    for path, is_dir in walk_paths(
        root, include_hidden=include_hidden, max_depth=max_depth, stats=stats
    ):
        if not name_matches(path.name, pattern, use_glob=use_glob, ignore_case=ignore_case):
            continue
        if exts and (is_dir or path.suffix.casefold() not in exts):
            continue
        if stats is not None:
            stats.matches += 1
        yield NameHit(
            path=path, is_dir=is_dir, is_symlink=path.is_symlink(), size_bytes=file_size(path)
        )
        if limit is not None and limit > 0 and stats is not None and stats.matches >= limit:
            stats.stopped_early = f"match limit {limit} reached"
            return


def is_binary_head(head: bytes) -> bool:
    """The NUL sniff. Text formats people edit do not contain NUL; executables do."""
    return b"\x00" in head


def decode_bytes(data: bytes) -> tuple[str, str]:
    """utf-8, then cp1252, then latin-1 with replacement.

    cp1252 sits second because this is a Windows-first tool and legacy files really are
    cp1252. latin-1 decodes any byte sequence so it never raises - the label says the
    result may be lossy instead of pretending it is exact.
    """
    for encoding in ENCODING_CHAIN:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1 (lossy)"


def search_contents(
    root: Path,
    pattern: str,
    *,
    use_regex: bool = False,
    ignore_case: bool = True,
    include_hidden: bool = False,
    extensions: Sequence[str] = (),
    max_depth: int | None = None,
    max_bytes: int = DEFAULT_GREP_MAX_BYTES,
    limit: int | None = None,
    stats: ScanStats | None = None,
) -> Iterator[Hit]:
    """Line-oriented content search over the tree.

    Skipped, and counted in `stats` rather than hidden: directories, symlinks (their
    payload may live outside the root we promised to search), files over `max_bytes`,
    and any file whose head contains NUL.
    """
    import re

    exts = normalize_extensions(extensions)
    flags = re.IGNORECASE if ignore_case else 0
    needle = pattern.casefold() if ignore_case else pattern
    matcher = re.compile(pattern, flags).search if use_regex else None

    for path, is_dir in walk_paths(
        root, include_hidden=include_hidden, max_depth=max_depth, stats=stats
    ):
        if is_dir:
            continue
        if os.path.islink(path):
            if stats is not None:
                stats.skipped_symlink += 1
            continue
        if exts and path.suffix.casefold() not in exts:
            continue
        size = file_size(path)
        if max_bytes and size > max_bytes:
            if stats is not None:
                stats.skipped_too_large += 1
            continue
        try:
            with path.open("rb") as handle:
                if is_binary_head(handle.read(SNIFF_BYTES)):
                    if stats is not None:
                        stats.skipped_binary += 1
                    continue
                handle.seek(0)
                for number, raw_line in enumerate(handle, start=1):
                    text, _ = decode_bytes(raw_line.rstrip(b"\r\n"))
                    if matcher is not None:
                        hit = matcher(text) is not None
                    elif ignore_case:
                        hit = needle in text.casefold()
                    else:
                        hit = needle in text
                    if not hit:
                        continue
                    if stats is not None:
                        stats.matches += 1
                    yield ContentHit(path=path, line_number=number, text=text)
                    if (
                        limit is not None
                        and limit > 0
                        and stats is not None
                        and stats.matches >= limit
                    ):
                        stats.stopped_early = f"match limit {limit} reached"
                        return
        except OSError as exc:
            if stats is not None:
                stats.unreadable += 1
                stats.errors.append(printable(f"{path}: {exc.strerror or exc}"))


# ---------------------------------------------------------------------------
# preview


@dataclass(frozen=True, slots=True)
class PreviewResult:
    path: Path
    entry: EntryStat
    kind: str
    encoding: str
    lines: tuple[str, ...]
    truncated: bool
    line_count: int | None
    counted: bool


def count_lines(path: Path, *, max_bytes: int = LINE_COUNT_MAX_BYTES) -> tuple[int | None, bool]:
    """`(lines, counted)`. Huge or unreadable files report None instead of stalling."""
    if os.path.islink(path) or file_size(path) > max_bytes:
        return None, False
    total = 0
    ends_with_newline = True
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                total += chunk.count(b"\n")
                ends_with_newline = chunk.endswith(b"\n")
    except OSError:
        return None, False
    if total and not ends_with_newline:
        total += 1
    return total, True


def preview(
    path: Path,
    lines: int = 20,
    *,
    count_line_total: bool = True,
    count_max_bytes: int = LINE_COUNT_MAX_BYTES,
) -> PreviewResult:
    """The head of a text file, or an honest metadata record for anything else.

    "Anything else" means a directory, a binary file, a link or something we cannot
    read: we print what the OS says about it rather than dumping replacement characters
    and letting the user guess.
    """
    entry = stat_entry(path)
    if entry.is_dir:
        return PreviewResult(path, entry, "directory", "", (), False, None, False)
    if not entry.is_file:
        return PreviewResult(path, entry, entry.kind, "", (), False, None, False)

    total, counted = (
        count_lines(path, max_bytes=count_max_bytes) if count_line_total else (None, False)
    )
    try:
        with path.open("rb") as handle:
            chunk = handle.read(HEAD_BUDGET)
            has_more = bool(handle.read(1))
    except OSError as exc:
        raise FilesError(f"cannot read {printable(path)}: {exc.strerror or exc}") from exc

    if is_binary_head(chunk):
        return PreviewResult(path, entry, "binary", "", (), False, total, counted)

    text, encoding = decode_bytes(chunk)
    rows = text.splitlines()
    if lines > 0:
        shown = rows[:lines]
        truncated = len(rows) > lines or has_more
    else:
        shown, truncated = rows, has_more
    return PreviewResult(
        path=path,
        entry=entry,
        kind="text",
        encoding=encoding,
        lines=tuple(shown),
        truncated=truncated,
        line_count=total,
        counted=counted,
    )


# ---------------------------------------------------------------------------
# copy / move / rename / delete


@dataclass(frozen=True, slots=True)
class OpResult:
    """What a mutating command actually did, so the renderer can say it back exactly."""

    verb: str
    source: Path
    destination: Path
    bytes_moved: int
    forced: bool


def tree_size(path: Path) -> int:
    """Bytes held by a tree, counting links as zero (their payload is not ours to move)."""
    if os.path.islink(path):
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(str(path), followlinks=False):
        for name in filenames:
            child = Path(dirpath) / name
            if not os.path.islink(child):
                with suppress(OSError):
                    total += int(os.lstat(child).st_size)
    return total


def plan_destination(source: Path, raw_dst: str | os.PathLike[str], *, root: Path | None) -> Path:
    """Where a write may land. An existing directory means "inside it", as `cp` does."""
    dst = resolve(raw_dst, root=root, label="destination")
    if dst == source:
        raise RequestError("source and destination are the same entry")
    if dst.is_dir():
        target = dst / source.name
        return resolve(target, root=root, label="destination")
    return dst


def _refuse_nesting(source: Path, target: Path, *, verb: str) -> None:
    if source.is_dir() and is_within(target, source):
        raise RequestError(
            f"cannot {verb} {printable(source)} into itself: the destination is inside the source"
        )


def _conflict(target: Path, *, force: bool, verb: str) -> None:
    if os.path.lexists(target) and not force:
        raise RequestError(
            f"destination already exists: {printable(target)}",
            hint=f"pass --force to replace it ({verb} will still ask you to confirm)",
        )


def _explain(exc: BaseException) -> str:
    """One readable line from an exception whose payload may be a list of failures.

    `shutil.Error` carries a list of `(source, destination, reason)` triples when a
    `copytree` half-fails; showing that repr is not a message a user can act on.
    """
    parts: list[str] = []
    for group in exc.args:
        if isinstance(group, (list, tuple)):
            for item in group:
                parts.append(str(item[-1]) if isinstance(item, (list, tuple)) else str(item))
        else:
            parts.append(str(group))
    return "; ".join(parts[:3]) or exc.__class__.__name__


def _perform(
    verb: str,
    source: Path,
    target: Path,
    action: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> None:
    """Run the mutation, turning the OS's answer into a LEVIX error.

    A refusal from the filesystem - a locked file, a full disk, a directory in the way -
    is an ordinary user outcome on Windows and must end as one message and exit 1, never
    as a traceback.
    """
    try:
        action(*args, **kwargs)
    except (OSError, shutil.Error) as exc:
        detail = printable(getattr(exc, "strerror", None) or _explain(exc))
        raise FilesError(
            f"cannot {verb} {printable(source)} -> {printable(target)}: {detail}",
            hint="check permissions, free space, and that no program is holding the file open",
        ) from exc


def copy_entry(
    source_raw: str | os.PathLike[str],
    dest_raw: str | os.PathLike[str],
    *,
    root: Path | None = None,
    force: bool = False,
) -> OpResult:
    """Copy a file, or a whole tree with `shutil.copytree(symlinks=True)`.

    `symlinks=True` recreates links as links instead of pulling in whatever they point
    at, which is faster and the only choice that cannot silently duplicate data the
    user did not ask to read. The source is read with no wall (copying *from* anywhere
    is what the user named); the destination always faces the wall.
    """
    source = require_exists(resolve(source_raw), label="source")
    target = plan_destination(source, dest_raw, root=root)
    _refuse_nesting(source, target, verb="copy")
    _conflict(target, force=force, verb="copy")
    if source.is_dir():
        _perform(
            "copy",
            source,
            target,
            shutil.copytree,
            source,
            target,
            symlinks=True,
            dirs_exist_ok=force,
        )
    else:
        _perform("copy", source, target, shutil.copy2, source, target)
    moved = tree_size(target) if target.is_dir() else file_size(target)
    return OpResult("copied", source, target, moved, force)


def move_entry(
    source_raw: str | os.PathLike[str],
    dest_raw: str | os.PathLike[str],
    *,
    root: Path | None = None,
    force: bool = False,
) -> OpResult:
    """Move within or across filesystems; `shutil.move` handles both, including copy+delete."""
    source = require_exists(resolve(source_raw), label="source")
    target = plan_destination(source, dest_raw, root=root)
    _refuse_nesting(source, target, verb="move")
    _conflict(target, force=force, verb="move")
    moved = tree_size(source) if source.is_dir() else file_size(source)
    if force and target.is_file():
        # shutil.move falls through to os.rename, which Windows refuses when the target
        # exists; --force is precisely the case where it does.
        _perform("move", source, target, os.replace, source, target)
    else:
        _perform("move", source, target, shutil.move, str(source), str(target))
    return OpResult("moved", source, target, moved, force)


def rename_entry(
    path_raw: str | os.PathLike[str],
    new_name: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> OpResult:
    """Rename in place.

    `validate_new_name` forbids separators, so a rename can never turn into a move and
    the entry's own directory *is* the wall. `--root`, when given, is checked on top.
    """
    name = validate_new_name(new_name)
    source = require_exists(to_path(path_raw).resolve(strict=False), label="path")
    wall = root if root is not None else source.parent
    source = resolve(path_raw, root=wall, label="path")
    target = resolve(source.parent / name, root=wall, label="destination")
    if target == source:
        raise RequestError("the new name is the name the entry already has")
    _conflict(target, force=force, verb="rename")
    # os.rename refuses an existing target on Windows (and on every POSIX system, where
    # it silently replaces it). os.replace is the one call that means the same thing on
    # both, so a forced rename only runs when the target is a file.
    if force and target.is_dir():
        raise RequestError(
            f"cannot rename onto the directory {printable(target)}: "
            "remove it first, or move the entry inside it with `levix files move`"
        )
    _perform("rename", source, target, os.replace if force else os.rename, source, target)
    size = tree_size(target) if target.is_dir() else file_size(target)
    return OpResult("renamed", source, target, size, force)


@dataclass(frozen=True, slots=True)
class DeleteItem:
    path: Path
    is_dir: bool
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DeletePlan:
    """Everything `delete` would remove, measured *before* it happens.

    The user confirms against these numbers, so they have to be the real ones.
    """

    roots: tuple[Path, ...]
    items: tuple[DeleteItem, ...]
    wall: Path
    covered: tuple[Path, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    @property
    def file_count(self) -> int:
        return sum(1 for item in self.items if not item.is_dir)

    @property
    def dir_count(self) -> int:
        return sum(1 for item in self.items if item.is_dir)

    @property
    def has_tree(self) -> bool:
        """Any root had at least one descendant, i.e. this was a recursive delete."""
        return len(self.items) > len(self.roots)

    def describe(self) -> str:
        return (
            f"{self.file_count} file(s) and {self.dir_count} directory(ies), "
            f"{human_bytes(self.total_bytes)} under {printable(self.wall)}"
        )


def collect_tree(top: Path) -> list[DeleteItem]:
    """Descendants of `top` in safe removal order (children before their directory).

    `topdown=False` gives that order for free. Symlinked directories appear as leaves,
    so a link is removed as a link and never walked into.
    """
    if os.path.islink(top):
        return [DeleteItem(top, False, 0)]
    if not top.is_dir():
        return [DeleteItem(top, False, file_size(top))]
    items: list[DeleteItem] = []
    for dirpath, dirnames, filenames in os.walk(str(top), topdown=False, followlinks=False):
        current = Path(dirpath)
        for name in sorted(filenames, key=lambda text: text.casefold()):
            child = current / name
            items.append(DeleteItem(child, False, file_size(child)))
        for name in sorted(dirnames, key=lambda text: text.casefold()):
            child = current / name
            if os.path.islink(child):
                items.append(DeleteItem(child, False, 0))
        items.append(DeleteItem(current, True, 0))
    return items


def plan_delete(raw_paths: Sequence[str], *, root: Path, recursive: bool) -> DeletePlan:
    """Validate a batch of deletions and measure it. Raises before anything is removed."""
    wall = root.resolve(strict=False)
    roots: list[Path] = []
    covered: list[Path] = []
    for raw in raw_paths:
        path = require_exists(
            resolve(raw, root=wall, label="deletion target"), label="deletion target"
        )
        if any(other != path and is_within(path, other) for other in roots):
            covered.append(path)
            continue
        roots.append(path)

    items: list[DeleteItem] = []
    for top in roots:
        if os.path.islink(top) or not top.is_dir():
            items.extend(collect_tree(top))
            continue
        children = entries_in(top)
        if children and not recursive:
            raise RequestError(
                f"{printable(top)} is a directory with {len(children)} entry(ies) inside",
                hint="deleting a tree cannot be undone; re-run with --recursive to say so",
            )
        items.extend(collect_tree(top))
    return DeletePlan(roots=tuple(roots), items=tuple(items), wall=wall, covered=tuple(covered))


def remove_entry(item: DeleteItem) -> None:
    """Delete one already-planned entry. Links go as links, directories only when empty."""
    path = item.path
    if os.path.islink(path):
        # A link to a directory must be removed with rmdir on Windows (os.remove raises
        # access denied there) and with unlink on POSIX (rmdir refuses a link there).
        if os.path.isdir(path):
            with suppress(OSError):
                os.unlink(path)
            if os.path.lexists(path):
                os.rmdir(path)
        else:
            os.unlink(path)
        return
    if item.is_dir:
        os.rmdir(path)
        return
    os.unlink(path)


def _remove_quietly(item: DeleteItem, failures: list[str]) -> bool:
    try:
        remove_entry(item)
    except OSError as exc:
        failures.append(printable(f"{item.path}: {exc.strerror or exc}"))
        return False
    return True


def execute_delete(plan: DeletePlan) -> tuple[list[DeleteItem], int, list[str]]:
    """Remove the planned items.

    A locked or in-use file - normal on Windows - is reported per entry while the rest
    of the batch continues, so the summary says exactly what is gone and what is not.
    """
    removed: list[DeleteItem] = []
    failures: list[str] = []
    reclaimed = 0
    for item in plan.items:
        if _remove_quietly(item, failures):
            removed.append(item)
            reclaimed += item.size_bytes
    return removed, reclaimed, failures

"""Reading local system state for `levix hacker`.

Everything here returns plain data and `cli.py` owns the rendering, so every address
and every frame below is unit-testable without a console. Two rules hold.

Honesty. A field is either parsed from a real source or it stays None and the renderer
says so. Nothing in this file substitutes `0.0.0.0`, an empty MAC or a plausible
adapter name for a value it could not read.

Local only. The helpers run read-only reporting tools (`ipconfig`, `route`, `ip`,
`ifconfig`) with `shell=False` and open a couple of well-known configuration files.
They never open a socket, never resolve a name through the network stack
(`socket.getfqdn` is unused on purpose because it can reach DNS), never send a packet
and never write anything.
"""

from __future__ import annotations

import codecs
import getpass
import itertools
import locale
import os
import platform
import random
import re
import shutil
import socket
import string
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ----------------------------------------------------------------------------------
# Matrix rain
# ----------------------------------------------------------------------------------

BLANK: Final = 0
FAINT: Final = 1
TAIL: Final = 2
NEAR: Final = 3
HEAD: Final = 4

RAIN_CHARS: Final = string.digits
FAINT_AFTER: Final = 5
FLICKER_CHANCE: Final = 0.02
MIN_SPEED: Final = 0.4
MAX_SPEED: Final = 1.4
MIN_TRAIL: Final = 3
MAX_TRAIL: Final = 18


@dataclass(frozen=True, slots=True)
class Frame:
    """One grid: `rows` holds the glyphs, `levels` the brightness of each cell.

    Keeping the two apart lets the renderer add colour without the simulation importing
    Rich, and lets a test compare a whole frame exactly.
    """

    rows: tuple[str, ...]
    levels: tuple[tuple[int, ...], ...]

    @property
    def width(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self) -> int:
        return len(self.rows)

    @property
    def lit_cells(self) -> int:
        return sum(1 for row in self.levels for level in row if level != BLANK)


@dataclass(slots=True)
class _Drop:
    """A falling trail. `glyphs[0]` is the head, so a trail keeps its characters as it
    moves instead of scrambling like television static."""

    position: float
    speed: float
    glyphs: list[str]

    def flicker(self, rng: random.Random, charset: str) -> None:
        """Swap one trail character, the way the film's columns glitch."""
        spot = rng.randrange(len(self.glyphs))
        self.glyphs[spot] = rng.choice(charset)


class MatrixScene:
    """Deterministic Matrix rain: same seed, same grid, same frames, every time.

    All randomness comes from the owned `random.Random` (never global state) and the
    generator is consumed in a fixed order - one draw per column for the spawn test,
    then one per live drop, then one per flickering trail - which is what makes a
    seeded run reproducible.
    """

    def __init__(
        self,
        *,
        columns: int,
        rows: int,
        density: float,
        head_char: str = "#",
        near_char: str = "+",
        charset: str = RAIN_CHARS,
        seed: int | None = None,
    ) -> None:
        if columns < 1 or rows < 1:
            msg = f"the rain needs at least one cell, got {columns}x{rows}"
            raise ValueError(msg)
        if not 0.0 < density <= 1.0:
            msg = f"density must be greater than 0 and at most 1, got {density}"
            raise ValueError(msg)
        if len(head_char) != 1 or len(near_char) != 1:
            msg = "the head and near characters must be exactly one cell wide"
            raise ValueError(msg)
        self.columns = columns
        self.rows = rows
        self.density = density
        self.head_char = head_char
        self.near_char = near_char
        self.charset = charset or RAIN_CHARS
        # The rain is decoration: a seeded PRNG is exactly what we want here, because it
        # makes a frame sequence reproducible for a given seed. Nothing security-relevant
        # is drawn from it.
        self._rng = random.Random(seed)  # noqa: S311
        self._drops: list[_Drop | None] = [None] * columns

    @property
    def active_columns(self) -> int:
        return sum(1 for drop in self._drops if drop is not None)

    def prime(self) -> None:
        """Start with the rain already falling instead of an empty screen.

        The spawn test is the same one `tick()` uses; only the head position differs, so
        a freshly constructed scene looks like the effect has been running for a screen
        worth of frames. Deterministic for a given seed, because it draws from the same
        generator in the same column order.
        """
        chance = min(1.0, self.density * self.rows / 2)
        for index, drop in enumerate(self._drops):
            if drop is not None:
                continue
            if self._rng.random() < chance:
                seeded = self._new_drop()
                seeded.position = self._rng.uniform(0.0, float(self.rows))
                self._drops[index] = seeded

    def _new_drop(self) -> _Drop:
        """Draw speed, then length, then the trail: that order is the seed contract."""
        shortest = min(MIN_TRAIL, self.rows)
        longest = min(MAX_TRAIL, max(shortest, self.rows))
        speed = self._rng.uniform(MIN_SPEED, MAX_SPEED)
        length = self._rng.randint(shortest, longest)
        return _Drop(
            position=0.0,
            speed=speed,
            glyphs=[self._rng.choice(self.charset) for _ in range(length)],
        )

    def _advance(self) -> None:
        for index, drop in enumerate(self._drops):
            if drop is None:
                if self._rng.random() < self.density:
                    self._drops[index] = self._new_drop()
                continue
            drop.position += drop.speed
            if drop.position - len(drop.glyphs) > self.rows:
                self._drops[index] = None
            elif self._rng.random() < FLICKER_CHANCE:
                drop.flicker(self._rng, self.charset)

    def _paint(self) -> Frame:
        grid = [[" "] * self.columns for _ in range(self.rows)]
        levels = [[BLANK] * self.columns for _ in range(self.rows)]
        for column, drop in enumerate(self._drops):
            if drop is None:
                continue
            head_row = int(drop.position)
            for offset, glyph in enumerate(drop.glyphs):
                row = head_row - offset
                if row < 0:
                    break
                if row >= self.rows:
                    continue
                if offset == 0:
                    grid[row][column] = self.head_char
                    levels[row][column] = HEAD
                elif offset == 1:
                    grid[row][column] = self.near_char
                    levels[row][column] = NEAR
                else:
                    grid[row][column] = glyph
                    levels[row][column] = TAIL if offset <= FAINT_AFTER else FAINT
        return Frame(
            rows=tuple("".join(line) for line in grid),
            levels=tuple(tuple(line) for line in levels),
        )

    def tick(self) -> Frame:
        """Advance the simulation by one frame and return it."""
        self._advance()
        return self._paint()


def run_frames(scene: MatrixScene, count: int) -> list[Frame]:
    """Tick `count` times. Shared with the tests so they drive the same path."""
    return [scene.tick() for _ in range(count)]


# ----------------------------------------------------------------------------------
# Running an OS reporting tool
# ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What happened when we tried to run a system tool.

    `available` answers "is the program on PATH"; `usable` answers "did it produce
    output we can parse". Commands report the difference instead of printing an empty
    table when the answer is no.
    """

    argv: tuple[str, ...]
    path: str | None
    returncode: int | None
    text: str | None
    note: str | None

    @property
    def available(self) -> bool:
        return self.path is not None

    @property
    def usable(self) -> bool:
        return self.returncode == 0 and bool(self.text)

    @classmethod
    def unavailable(cls, argv: Sequence[str], note: str) -> ToolResult:
        return cls(tuple(str(part) for part in argv), None, None, None, note)


def _decode_candidates() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        # Console tools answer in the OEM codepage, not the ANSI one Python's locale
        # settings report, so "oem" has to be tried first or the leaders turn to noise.
        return ("oem", "cp850", "cp437", locale.getpreferredencoding(False))
    return (locale.getpreferredencoding(False), "utf-8")


def _decode_with(raw: bytes, encoding: str) -> str | None:
    try:
        codecs.lookup(encoding)
    except LookupError:
        return None
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return None


def decode_console_output(raw: bytes) -> str:
    """Decode tool output without ever raising on an unexpected byte."""
    for encoding in _decode_candidates():
        text = _decode_with(raw, encoding)
        if text is not None:
            return text
    return raw.decode("utf-8", errors="replace")


def run_tool(argv: Sequence[str], *, timeout: float = 8.0) -> ToolResult:
    """Run a program with an argument list. Never a shell, never a command string."""
    command = [str(part) for part in argv]
    path = shutil.which(command[0])
    if path is None:
        return ToolResult.unavailable(command, f"{command[0]} is not on PATH")
    # Execute exactly what the PATH lookup found instead of letting the OS resolve the
    # bare name again: the two searches can disagree. `program` stays a list and `shell`
    # stays False, so no part of the argv is ever re-parsed by a command interpreter.
    program = [path, *command[1:]]
    try:
        completed = subprocess.run(
            program,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tuple(command), path, None, None, f"{command[0]} timed out after {timeout}s"
        )
    except OSError as exc:
        return ToolResult(tuple(command), path, None, None, f"could not run {command[0]}: {exc}")

    text = decode_console_output(completed.stdout).strip()
    if completed.returncode != 0:
        detail = decode_console_output(completed.stderr).strip()
        note = f"{command[0]} exited {completed.returncode}"
        return ToolResult(
            tuple(command),
            path,
            completed.returncode,
            text or None,
            f"{note}: {detail}" if detail else note,
        )
    if not text:
        return ToolResult(
            tuple(command),
            path,
            completed.returncode,
            None,
            f"{command[0]} produced no output",
        )
    return ToolResult(tuple(command), path, completed.returncode, text, None)


# ----------------------------------------------------------------------------------
# Small parsing helpers
# ----------------------------------------------------------------------------------

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_HEX_GROUP_RE = re.compile(r"^[0-9A-Fa-f]{1,4}$")
_ANNOTATION_RE = re.compile(
    r"\s*\((?:Preferred|Temporary|Deprecated|Tentative|Duplicate|Invalid)\)\s*$",
    re.IGNORECASE,
)
# Route tables spell the default route as `0.0.0.0/0.0.0.0` and put `0.0.0.0` in the
# gateway column to mean "directly connected". This literal is text we parse plus one
# argument we hand to `route print`; the module never binds or connects a socket, so the
# bandit warning about listening on all interfaces does not apply here.
ANY_IPV4: Final = "0.0.0.0"  # noqa: S104


def looks_like_ipv4(value: str) -> bool:
    """A dotted quad, optionally carrying the CIDR length `ip` prints with it."""
    body = value.split("/", 1)[0]
    if not _IPV4_RE.match(body):
        return False
    return all(int(part) <= 255 for part in body.split("."))


def looks_like_ipv6(value: str) -> bool:
    """A shape test, not a full parser: enough to tell an address from prose."""
    address = value.split("/", 1)[0].split("%", 1)[0]
    if ":" not in address or address.count("::") > 1:
        return False

    def group_ok(group: str) -> bool:
        return bool(_HEX_GROUP_RE.match(group)) or looks_like_ipv4(group)

    if address.count("::") == 1:
        left, _, right = address.partition("::")
        groups = [part for part in left.split(":") + right.split(":") if part]
        return all(group_ok(group) for group in groups) and len(groups) <= 7
    groups = address.split(":")
    return len(groups) == 8 and all(group_ok(group) for group in groups)


def looks_like_address(value: str) -> bool:
    return looks_like_ipv4(value) or looks_like_ipv6(value)


def address_family(value: str) -> str:
    if looks_like_ipv4(value):
        return "ipv4"
    if looks_like_ipv6(value):
        return "ipv6"
    return "other"


def strip_annotation(value: str) -> str:
    """`192.168.87.4(Preferred)` -> `192.168.87.4`."""
    return _ANNOTATION_RE.sub("", value).strip()


def yes_no(value: str) -> bool | None:
    folded = value.strip().casefold()
    if folded in {"yes", "true", "enabled", "on"}:
        return True
    if folded in {"no", "false", "disabled", "off"}:
        return False
    return None


def int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def normalise_mac(raw: str) -> str | None:
    """`3c-55-76-ce-a4-6b`, `3c:55:...`, `3c55.76ce.a46b` -> `3C:55:76:CE:A4:6B`.

    Anything that is not exactly twelve hex digits returns None: a truncated or
    wildcarded value is reported as absent rather than shown as a fake address.
    """
    digits = re.sub(r"[^0-9a-fA-F]", "", raw)
    if len(digits) != 12:
        return None
    return ":".join(digits[index : index + 2] for index in range(0, 12, 2)).upper()


def normalise_prefix(raw: str | None) -> str | None:
    """Report a netmask as a CIDR length when the source used a mask.

    `ip` gives `24`, `ipconfig` gives `255.255.255.0` and old `ifconfig` gives
    `0xffffff00`. One output format, derived from the value that was actually reported.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.isdigit():
        return str(int(value))
    body = value[2:] if value.lower().startswith("0x") else value
    bits: str | None = None
    if looks_like_ipv4(body):
        bits = "".join(f"{int(part):08b}" for part in body.split("."))
    elif re.fullmatch(r"[0-9a-fA-F]{8}", body):
        bits = "".join(f"{int(body[index : index + 2], 16):08b}" for index in range(0, 8, 2))
    if bits is None:
        return value
    leading = bits.rstrip("0")
    # Only a real netmask (a run of ones, then nothing but zeros) becomes a length; a
    # value like `255.255.255.1` is passed through unchanged rather than reported as a
    # prefix it never was.
    if set(leading) - {"1"}:
        return value
    return str(len(leading))


# ----------------------------------------------------------------------------------
# The network model
# ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NetAddress:
    address: str
    family: str
    kind: str
    prefix: str | None = None

    @property
    def reported(self) -> str:
        return f"{self.address}/{self.prefix}" if self.prefix else self.address


@dataclass(frozen=True, slots=True)
class Interface:
    name: str
    kind: str | None
    description: str | None
    mac: str | None
    state: str | None
    dhcp: bool | None
    gateway: str | None
    dns: tuple[str, ...]
    suffix: str | None
    netbios: str | None
    addresses: tuple[NetAddress, ...]
    source: str

    @property
    def is_loopback(self) -> bool:
        if self.kind == "loopback":
            return True
        return any(
            address.address.startswith("127.") or address.address in {"::1", "::"}
            for address in self.addresses
        )

    @property
    def addresses_text(self) -> str:
        return ", ".join(address.reported for address in self.addresses) or "-"

    @property
    def reported_state(self) -> str:
        return self.state or "-"

    @property
    def reported_mac(self) -> str:
        return self.mac or "-"


@dataclass(frozen=True, slots=True)
class Route:
    destination: str
    prefix: str | None
    gateway: str | None
    interface: str | None
    metric: int | None
    family: str
    source: str

    @property
    def is_default(self) -> bool:
        """True for the catch-all route, in whatever spelling the tool used.

        Windows' `route print` writes destination `0.0.0.0` with netmask `0.0.0.0`, Linux
        `route -n` writes the same pair, and `ip route` writes the word `default`.
        """
        if self.destination not in {"default", ANY_IPV4, "::/0"}:
            return False
        return self.prefix in {None, "0", ANY_IPV4}


@dataclass(frozen=True, slots=True)
class Gateway:
    """A default-gateway candidate together with the source that reported it.

    `on_link` means the route table printed `0.0.0.0` in the gateway column: the
    destination is directly connected and there is no gateway hop. That is a real
    answer, distinct from "we could not read one".
    """

    address: str | None
    interface: str | None
    metric: int | None
    source: str
    on_link: bool = False

    @property
    def reported(self) -> str:
        if self.on_link:
            return f"directly connected on {self.interface or 'an unknown interface'}"
        if not self.address:
            return "not reported"
        where = f" via {self.interface}" if self.interface else ""
        return f"{self.address}{where}"


@dataclass(frozen=True, slots=True)
class DnsServer:
    address: str
    source: str


@dataclass(frozen=True, slots=True)
class ResolutionStep:
    position: int
    label: str
    detail: str
    evidence: str


@dataclass(frozen=True, slots=True)
class HostsFile:
    path: str
    exists: bool
    mappings: int | None
    note: str | None


@dataclass(frozen=True, slots=True)
class IpconfigSummary:
    interfaces: tuple[Interface, ...]
    hostname: str | None
    primary_dns_suffix: str | None
    node_type: str | None
    ip_routing: bool | None
    wins_proxy: bool | None


@dataclass(frozen=True, slots=True)
class NetworkView:
    """One machine's network configuration plus the evidence behind every field."""

    system: str
    interface_source: str | None
    interfaces: tuple[Interface, ...]
    routes: tuple[Route, ...]
    gateways: tuple[Gateway, ...]
    dns: tuple[DnsServer, ...]
    resolution: tuple[ResolutionStep, ...]
    hosts: HostsFile | None
    suffixes: tuple[str, ...]
    tools: tuple[ToolResult, ...]
    notes: tuple[str, ...]

    @property
    def selected_gateway(self) -> Gateway | None:
        return self.gateways[0] if self.gateways else None

    def tool(self, name: str) -> ToolResult | None:
        for result in self.tools:
            if result.argv and result.argv[0].casefold().endswith(name.casefold()):
                return result
        return None

    def missing_data_notes(self) -> tuple[str, ...]:
        return tuple(self.notes)


# ----------------------------------------------------------------------------------
# Windows: ipconfig /all and route print
# ----------------------------------------------------------------------------------


def split_key_line(line: str) -> tuple[str, str] | None:
    """`   Physical Address. . . . : 3C-55-76` -> `('physicaladdress', '3C-55-76')`.

    ipconfig separates a label from its value with a run of dot leaders, and the value
    can itself contain a colon (lease timestamps), so only the first colon splits.
    """
    if ":" not in line:
        return None
    head, _, tail = line.partition(":")
    key = re.sub(r"[.\s\-]+", "", head)
    if not key:
        return None
    return key.casefold(), tail.strip()


def _is_section_header(line: str) -> bool:
    """An adapter block starts with an unindented line ending in a colon."""
    return bool(line) and not line[0].isspace() and line.rstrip().endswith(":")


def _adapter_identity(header: str) -> tuple[str, str | None]:
    """`Wireless LAN adapter Wi-Fi:` -> `('Wi-Fi', 'Wireless LAN')`."""
    label = header.strip().rstrip(":")
    if " adapter " in label:
        kind, _, name = label.partition(" adapter ")
        return name.strip(), kind.strip()
    return label, None


@dataclass(slots=True)
class _AdapterDraft:
    """Accumulates an adapter's raw keys, then turns them into an `Interface`.

    The draft is mutable on purpose: ipconfig prints the subnet mask after the IPv4
    address, so the prefix can only be attached once the whole block has been read.
    """

    name: str
    source: str
    kind: str | None = None
    state: str | None = None
    raw: dict[str, list[str]] = field(default_factory=dict)

    def add_addresses(self, values: Sequence[str], kind: str) -> list[NetAddress]:
        addresses: list[NetAddress] = []
        for value in values:
            address = strip_annotation(value)
            if not address or not looks_like_address(address):
                continue
            addresses.append(
                NetAddress(
                    address=address.split("/", 1)[0],
                    family=address_family(address),
                    kind=kind,
                    prefix=normalise_prefix(address.split("/", 1)[1]) if "/" in address else None,
                )
            )
        return addresses

    def build(self) -> Interface:
        values = {
            key: [item for item in listed if item.strip()] for key, listed in self.raw.items()
        }

        def scalar(key: str) -> str | None:
            found = values.get(key)
            return found[0] if found else None

        def flag(key: str) -> bool | None:
            return yes_no(scalar(key) or "")

        def extend(items: Sequence[str], kind: str) -> None:
            addresses.extend(self.add_addresses(items, kind))

        state = scalar("mediastate")
        if state and "disconnected" in state.casefold():
            state = "disconnected"
        addresses: list[NetAddress] = []
        extend(values.get("ipv4address", []), "configured")
        extend(values.get("autoconfigurationipv4address", []), "autoconfiguration")
        extend(values.get("ipv6address", []), "configured")
        extend(values.get("linklocalipv6address", []), "link-local")
        extend(values.get("temporaryipv6address", []), "temporary")
        prefix = normalise_prefix(scalar("subnetmask"))
        if prefix:
            for index, address in enumerate(addresses):
                if address.family == "ipv4" and address.prefix is None:
                    addresses[index] = NetAddress(
                        address=address.address,
                        family=address.family,
                        kind=address.kind,
                        prefix=prefix,
                    )
                    break
        return Interface(
            name=self.name,
            kind=self.kind,
            description=scalar("description"),
            mac=normalise_mac(scalar("physicaladdress") or ""),
            state=state,
            dhcp=flag("dhcpenabled"),
            gateway=(scalar("defaultgateway") or None),
            dns=tuple(item for item in values.get("dnsservers", []) if looks_like_address(item)),
            suffix=scalar("connectionspecificdnssuffix"),
            netbios=scalar("netbiosovertcpip"),
            addresses=tuple(addresses),
            source=self.source,
        )


def parse_ipconfig_all(text: str, *, source: str = "ipconfig /all") -> IpconfigSummary:
    """Parse `ipconfig /all`, or anything using the same label-dot-value layout.

    Only English-labelled output is matched, because the labels are the keys. On a
    localised Windows the honest result is "no adapters parsed", which the command
    reports instead of filling a table with guesses.
    """
    global_fields: dict[str, list[str]] = {}
    drafts: list[_AdapterDraft] = []
    target: dict[str, list[str]] = global_fields
    last_key: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            # A blank line ends a multi-valued field such as a second DNS server.
            last_key = None
            continue
        if _is_section_header(line):
            name, kind = _adapter_identity(stripped)
            draft = _AdapterDraft(name=name, source=source, kind=kind)
            drafts.append(draft)
            target = draft.raw
            last_key = None
            continue
        if not line[:1].isspace():
            last_key = None
            continue
        pair = split_key_line(stripped)
        if pair is None:
            if last_key is not None:
                # An indented line with no colon continues the value above it; this is
                # how ipconfig prints a second DNS server or a second gateway.
                target.setdefault(last_key, []).append(stripped)
            continue
        key, value = pair
        target.setdefault(key, []).append(value)
        last_key = key

    cleaned = {
        key: [item for item in listed if item.strip()] for key, listed in global_fields.items()
    }

    def scalar(key: str) -> str | None:
        found = cleaned.get(key)
        return found[0] if found else None

    return IpconfigSummary(
        interfaces=tuple(draft.build() for draft in drafts),
        hostname=scalar("hostname"),
        primary_dns_suffix=scalar("primarydnssuffix"),
        node_type=scalar("nodetype"),
        ip_routing=yes_no(scalar("iproutingenabled") or ""),
        wins_proxy=yes_no(scalar("winsproxyenabled") or ""),
    )


def _gateway_column(value: str) -> str | None:
    """Read a route-table gateway column without inventing an address.

    `0.0.0.0` in that column means the destination is directly connected, so there is no
    gateway hop to report. Anything that is not an address at all - the filler a tool
    uses for "no gateway" - is reported as None as well, instead of being printed as if
    it were a real host.
    """
    if value == ANY_IPV4:
        return None
    if looks_like_ipv4(value) or looks_like_ipv6(value):
        return value
    return None


def parse_route_print(text: str) -> list[Route]:
    """Parse the IPv4 table of `route print`, skipping the banner rules.

    A gateway column of `0.0.0.0` becomes "no gateway hop" rather than an address
    literally named 0.0.0.0.
    """
    routes: list[Route] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("IPv4 Route Table"):
            in_table = True
            continue
        if stripped.startswith("IPv6 Route Table"):
            in_table = False
            continue
        if not in_table:
            continue
        if stripped.startswith(("=", "Active Routes", "Persistent Routes", "Interface List")):
            continue
        if stripped.casefold() == "none" or stripped.startswith("Network Destination"):
            continue
        parts = stripped.split()
        if len(parts) != 5:
            continue
        destination, netmask, gateway, interface, metric = parts
        if not looks_like_ipv4(destination) or not looks_like_ipv4(netmask):
            continue
        routes.append(
            Route(
                destination=destination,
                prefix=netmask,
                interface=interface,
                gateway=_gateway_column(gateway),
                metric=int_or_none(metric),
                family="ipv4",
                source="route print",
            )
        )
    return routes


# ----------------------------------------------------------------------------------
# POSIX: ip, ifconfig, route and resolv.conf
# ----------------------------------------------------------------------------------

_IP_HEADER_RE = re.compile(r"^(?:\d+):\s*(?P<name>[^@\s:]+)(?:@\S+)?\s*:(?:\s*<(?P<flags>[^>]*)>)?")
_IP_STATE_RE = re.compile(r"\bstate\s+(?P<state>[A-Za-z]+)\b")
_IFCONFIG_HEADER_RE = re.compile(
    r"^(?P<name>[^\s:]+):?\s+flags=(?P<hex>\d+)(?:<(?P<flags>[^>]*)>)?"
)


def _apply_ip_tokens(draft: _AdapterDraft, parts: Sequence[str]) -> None:
    """Consume the address lines of `ip addr`, and the tail of an `-o` line."""
    if not parts:
        return
    keyword = parts[0]
    if keyword == "link/ether" and len(parts) > 1:
        draft.raw.setdefault("physicaladdress", []).append(parts[1])
    elif keyword == "inet" and len(parts) > 1:
        draft.raw.setdefault("ipv4address", []).append(parts[1])
    elif keyword == "inet6" and len(parts) > 1:
        key = "linklocalipv6address" if parts[1].lower().startswith("fe80") else "ipv6address"
        draft.raw.setdefault(key, []).append(parts[1])


def parse_ip_addr(text: str) -> list[Interface]:
    """Parse `ip addr show`. Also copes with `-o`, which prints one address per line.

    `eth0@if7` is the kernel's veth peer notation; the readable name is the part before
    the `@`, so that is what gets reported.
    """
    interfaces: list[Interface] = []
    draft: _AdapterDraft | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _IP_HEADER_RE.match(stripped)
        if header:
            if draft is not None:
                interfaces.append(draft.build())
            flags = (header.group("flags") or "").split(",")
            draft = _AdapterDraft(
                name=header.group("name"),
                source="ip addr",
                kind="loopback" if "LOOPBACK" in flags else None,
            )
            state = _IP_STATE_RE.search(stripped)
            reported = state.group("state").lower() if state else None
            readable = ",".join(flag for flag in flags if flag)
            draft.raw.setdefault("mediastate", []).append(reported or readable or "")
            _apply_ip_tokens(draft, stripped[header.end() :].split())
            continue
        if draft is None:
            continue
        _apply_ip_tokens(draft, stripped.split())

    if draft is not None:
        interfaces.append(draft.build())
    return interfaces


def _attribute_map(parts: Sequence[str]) -> dict[str, str]:
    """`key value` pairs of an `ip route` line: via, dev, metric, src ..."""
    return dict(itertools.pairwise(parts))


def parse_ip_route(text: str) -> list[Route]:
    """Parse `ip route show` / `ip -6 route show` output."""
    routes: list[Route] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        destination = parts[0]
        if destination == "default":
            target, prefix = "default", None
        elif "/" in destination:
            target, _, length = destination.partition("/")
            prefix = length or None
        else:
            continue
        attributes = _attribute_map(parts)
        gateway = attributes.get("via")
        if gateway is not None and not looks_like_address(gateway):
            gateway = None
        routes.append(
            Route(
                destination=target,
                prefix=prefix,
                gateway=gateway,
                interface=attributes.get("dev"),
                metric=int_or_none(attributes.get("metric")),
                family="ipv6" if ":" in target else "ipv4",
                source="ip route",
            )
        )
    return routes


def parse_ifconfig(text: str) -> list[Interface]:
    """Parse `ifconfig -a` (net-tools and macOS/BSD layouts)."""
    interfaces: list[Interface] = []
    draft: _AdapterDraft | None = None

    for line in text.splitlines():
        if not line[:1].isspace():
            header = _IFCONFIG_HEADER_RE.match(line.strip())
            if header:
                if draft is not None:
                    interfaces.append(draft.build())
                flags = (header.group("flags") or "").split(",")
                draft = _AdapterDraft(
                    name=header.group("name"),
                    source="ifconfig",
                    kind="loopback" if "LOOPBACK" in flags else None,
                )
                if flags and flags != [""]:
                    reported = "up" if "UP" in flags else "down"
                    draft.raw.setdefault("mediastate", []).append(
                        f"{reported} ({','.join(flag for flag in flags if flag)})"
                    )
            continue
        if draft is None:
            continue
        parts = line.strip().split()
        if not parts:
            continue
        keyword = parts[0]
        if keyword == "ether" and len(parts) > 1:
            draft.raw.setdefault("physicaladdress", []).append(parts[1])
        elif keyword == "inet" and len(parts) > 1:
            draft.raw.setdefault("ipv4address", []).append(parts[1])
            if "netmask" in parts:
                following = parts[parts.index("netmask") + 1 :]
                if following:
                    draft.raw.setdefault("subnetmask", []).append(following[0])
        elif keyword == "inet6" and len(parts) > 1:
            key = "linklocalipv6address" if parts[1].lower().startswith("fe80") else "ipv6address"
            draft.raw.setdefault(key, []).append(parts[1])

    if draft is not None:
        interfaces.append(draft.build())
    return interfaces


def parse_route_n(text: str) -> list[Route]:
    """Parse the Linux net-tools `route -n` table (eight columns)."""
    routes: list[Route] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 8:
            continue
        destination, gateway, netmask, _flags, metric, _ref, _use, interface = parts
        if not looks_like_ipv4(destination) or not looks_like_ipv4(netmask):
            continue
        routes.append(
            Route(
                destination=destination,
                prefix=netmask,
                gateway=_gateway_column(gateway),
                interface=interface,
                metric=int_or_none(metric),
                family="ipv4",
                source="route -n",
            )
        )
    return routes


def parse_route_get_default(text: str) -> list[Route]:
    """Parse BSD/macOS `route -n get default`, which is a `key: value` list."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        pair = split_key_line(line.strip())
        if pair:
            fields[pair[0]] = pair[1]
    gateway = fields.get("gateway")
    interface = fields.get("interface")
    if gateway is None and interface is None:
        return []
    usable = gateway if gateway and looks_like_address(gateway) else None
    return [
        Route(
            destination="default",
            prefix=None,
            gateway=usable,
            interface=interface,
            metric=int_or_none(fields.get("metric")),
            family="ipv6" if usable and looks_like_ipv6(usable) else "ipv4",
            source="route -n get default",
        )
    ]


def parse_resolv_conf(text: str) -> tuple[list[str], list[str]]:
    """(nameservers, search domains) in the order resolv.conf lists them."""
    servers: list[str] = []
    search: list[str] = []
    for line in text.splitlines():
        body = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not body:
            continue
        parts = body.split()
        directive = parts[0].casefold()
        if directive == "nameserver" and len(parts) > 1 and looks_like_address(parts[1]):
            servers.append(parts[1])
        elif directive == "search":
            search.extend(parts[1:])
        elif directive == "domain" and len(parts) > 1:
            search.append(parts[1])
    return servers, search


def parse_nsswitch_hosts(text: str) -> list[str]:
    """The `hosts:` line of nsswitch.conf - the real resolution order on most Linux."""
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        if not body.startswith("hosts:"):
            continue
        values = body.partition(":")[2].split()
        return [value for value in values if not value.startswith("[")]
    return []


# ----------------------------------------------------------------------------------
# Files this module reads (the whole list is here, on purpose)
# ----------------------------------------------------------------------------------

MAX_READ_BYTES = 262_144


def hosts_file_path() -> Path:
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
        return root / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def read_text_file(path: Path) -> tuple[str | None, str | None]:
    """Return (content, problem). Never raises: an unreadable file is a reported fact."""
    if not path.exists():
        return None, f"{path} does not exist"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_READ_BYTES), None
    except OSError as exc:
        return None, f"{path} could not be read ({type(exc).__name__})"


def read_hosts_file(path: Path | None = None) -> HostsFile:
    target = path or hosts_file_path()
    text, problem = read_text_file(target)
    if text is None:
        return HostsFile(str(target), False, None, problem)
    mappings = sum(
        1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    return HostsFile(str(target), True, mappings, None)


# ----------------------------------------------------------------------------------
# Facts about this host
# ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TerminalFacts:
    columns: int
    lines: int
    encoding: str
    isatty: bool
    term: str


@dataclass(frozen=True, slots=True)
class HostFacts:
    hostname: str
    hostname_source: str
    system: str
    release: str
    version: str
    machine: str
    processor: str
    python_version: str
    python_implementation: str
    executable: str
    pid: int
    user: str
    user_source: str
    cpu_count: int | None
    terminal: TerminalFacts


def local_hostname() -> tuple[str, str]:
    """The local node name only. `socket.getfqdn` is avoided: it queries DNS."""
    try:
        name = socket.gethostname()
    except OSError as exc:
        return platform.node(), f"socket.gethostname() failed ({exc}); platform.node() used"
    return (name or platform.node()), "socket.gethostname()"


def _posix_account() -> tuple[str | None, str]:
    try:
        import pwd
    except ImportError:
        return None, "the pwd module is unavailable"
    try:
        # Looked up by name rather than as an attribute: typeshed defines `os.getuid` and
        # the whole `pwd` module only for POSIX, so a checker running on Windows sees
        # neither and rejects the direct form. B009 wants the constant-`getattr` gone, and
        # its rewrite is exactly what breaks the check this line exists to pass.
        getuid = getattr(os, "getuid")  # noqa: B009
        getpwuid = getattr(pwd, "getpwuid")  # noqa: B009
        uid = getuid()
        return getpwuid(uid).pw_name, f"pwd entry for uid {uid}"
    except (OSError, KeyError, AttributeError) as exc:
        return None, f"pwd lookup failed ({exc})"


def current_user() -> tuple[str, str]:
    """(name, how it was obtained) - `getpass.getuser` reads environment variables."""
    if os.name == "posix":
        name, source = _posix_account()
        if name:
            return name, source
    for variable in ("USERNAME", "USER", "LOGNAME"):
        value = os.environ.get(variable)
        if value:
            return value, f"environment variable {variable}"
    try:
        return getpass.getuser(), "getpass.getuser()"
    except (OSError, KeyError, ValueError) as exc:
        return "(unknown)", f"no account could be determined ({exc})"


def terminal_facts() -> TerminalFacts:
    size = shutil.get_terminal_size(fallback=(80, 24))
    encoding = getattr(sys.stdout, "encoding", "") or "unknown"
    try:
        isatty = bool(sys.stdout.isatty())
    except (ValueError, OSError):
        isatty = False
    return TerminalFacts(
        columns=size.columns,
        lines=size.lines,
        encoding=encoding,
        isatty=isatty,
        term=os.environ.get("TERM", "(not set)"),
    )


def host_facts() -> HostFacts:
    uname = platform.uname()
    hostname, hostname_source = local_hostname()
    user, user_source = current_user()
    return HostFacts(
        hostname=hostname,
        hostname_source=hostname_source,
        system=uname.system or platform.system(),
        release=uname.release,
        version=uname.version,
        machine=uname.machine,
        processor=uname.processor,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        executable=sys.executable,
        pid=os.getpid(),
        user=user,
        user_source=user_source,
        cpu_count=os.cpu_count(),
        terminal=terminal_facts(),
    )


# ----------------------------------------------------------------------------------
# Cross-platform collection
# ----------------------------------------------------------------------------------


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _default_gateways(routes: Sequence[Route], interfaces: Sequence[Interface]) -> list[Gateway]:
    """Route-table defaults first (lowest metric wins), then per-interface gateways."""
    found: list[Gateway] = []
    defaults = [route for route in routes if route.is_default]
    defaults.sort(
        key=lambda route: (
            0 if route.family == "ipv4" else 1,
            route.metric if route.metric is not None else 2**31,
        )
    )
    for route in defaults:
        found.append(
            Gateway(
                address=route.gateway,
                interface=route.interface,
                metric=route.metric,
                source=route.source,
                on_link=route.gateway is None,
            )
        )
    for interface in interfaces:
        if not interface.gateway:
            continue
        if any(gateway.address == interface.gateway for gateway in found):
            continue
        found.append(
            Gateway(
                address=interface.gateway,
                interface=interface.name,
                metric=None,
                source=f"{interface.source} (per interface)",
            )
        )
    return found


def _dns_from_interfaces(interfaces: Sequence[Interface]) -> list[DnsServer]:
    servers: list[DnsServer] = []
    seen: set[str] = set()
    for interface in interfaces:
        for address in interface.dns:
            if address in seen:
                continue
            seen.add(address)
            servers.append(DnsServer(address, f"{interface.source} ({interface.name})"))
    return servers


def _dedupe_dns(servers: Sequence[DnsServer]) -> tuple[DnsServer, ...]:
    seen: set[str] = set()
    unique: list[DnsServer] = []
    for server in servers:
        if server.address in seen:
            continue
        seen.add(server.address)
        unique.append(server)
    return tuple(unique)


def _merge_interfaces(
    existing: Sequence[Interface], extra: Sequence[Interface]
) -> tuple[Interface, ...]:
    """Enrich adapters by name; anything unmatched is added, never dropped."""
    merged: list[Interface] = list(existing)
    by_name = {interface.name: index for index, interface in enumerate(merged)}
    for interface in extra:
        index = by_name.get(interface.name)
        if index is None:
            by_name[interface.name] = len(merged)
            merged.append(interface)
            continue
        current = merged[index]
        merged[index] = Interface(
            name=current.name,
            kind=current.kind or interface.kind,
            description=current.description or interface.description,
            mac=current.mac or interface.mac,
            state=current.state or interface.state,
            dhcp=current.dhcp if current.dhcp is not None else interface.dhcp,
            gateway=current.gateway or interface.gateway,
            dns=current.dns or interface.dns,
            suffix=current.suffix or interface.suffix,
            netbios=current.netbios or interface.netbios,
            addresses=current.addresses or interface.addresses,
            source=f"{current.source} + {interface.source}",
        )
    return tuple(merged)


def _windows_resolution(
    hosts: HostsFile,
    summary: IpconfigSummary | None,
    suffixes: Sequence[str],
    dns: Sequence[DnsServer],
) -> list[ResolutionStep]:
    """Steps 1 and 2 are what Windows documents; the values in every step are read from
    this machine. The ordering itself is not published by any local file, and the
    command says so rather than implying it parsed an order it did not read."""
    steps: list[ResolutionStep] = [
        ResolutionStep(
            position=1,
            label="hosts file",
            detail=(
                f"{hosts.path} with {hosts.mappings} static entries"
                if hosts.mappings is not None
                else f"{hosts.path} ({hosts.note or 'unavailable'})"
            ),
            evidence="file read directly",
        )
    ]
    if suffixes:
        steps.append(
            ResolutionStep(2, "DNS suffix search list", ", ".join(suffixes), "ipconfig /all")
        )
    steps.append(
        ResolutionStep(
            3,
            "DNS servers",
            ", ".join(server.address for server in dns) or "none reported",
            "ipconfig /all",
        )
    )
    node_type = summary.node_type if summary else None
    interfaces = summary.interfaces if summary else ()
    netbios = _dedupe([item.netbios for item in interfaces if item.netbios])
    if node_type or netbios:
        steps.append(
            ResolutionStep(
                4,
                "NetBIOS over TCP/IP",
                f"node type {node_type or 'not reported'}, adapters: "
                f"{', '.join(netbios) or 'not reported'}",
                "ipconfig /all",
            )
        )
    return steps


def _collect_windows(notes: list[str], tools: list[ToolResult]) -> NetworkView:
    ipconfig = run_tool(("ipconfig", "/all"))
    tools.append(ipconfig)
    summary: IpconfigSummary | None = None
    interfaces: tuple[Interface, ...] = ()
    if ipconfig.usable:
        summary = parse_ipconfig_all(ipconfig.text or "")
        interfaces = summary.interfaces
        if not interfaces:
            notes.append(
                "ipconfig /all ran but matched no adapter sections; on a localised "
                "Windows the labels differ, so nothing was parsed rather than guessed"
            )
    else:
        notes.append(
            f"ipconfig /all: {ipconfig.note or 'no output'} - interface, gateway and DNS "
            "data are unavailable, not empty"
        )

    adapter = run_tool(("getadapterconfig", "/all"))
    tools.append(adapter)
    if adapter.available and adapter.usable:
        extra = parse_ipconfig_all(adapter.text or "", source="getadapterconfig /all")
        interfaces = _merge_interfaces(interfaces, extra.interfaces)
        notes.append("getadapterconfig was found and merged into the interface list")
    elif adapter.available:
        notes.append(
            f"getadapterconfig ran but gave nothing parsable: {adapter.note or 'no output'}"
        )
    else:
        notes.append(
            "getadapterconfig is not installed (it is not a stock Windows program), so "
            "ipconfig /all is the only interface source here"
        )

    route = run_tool(("route", "print", ANY_IPV4))
    tools.append(route)
    routes: list[Route] = []
    if route.usable:
        routes = parse_route_print(route.text or "")
    else:
        notes.append(
            f"route print: {route.note or 'no output'} - the gateway can only come from "
            "ipconfig's per-adapter value"
        )

    hosts = read_hosts_file()
    if hosts.mappings is None:
        notes.append(f"hosts file: {hosts.note or 'unreadable'}")
    dns = _dedupe_dns(_dns_from_interfaces(interfaces))
    suffixes = _dedupe(
        [
            (summary.primary_dns_suffix or "") if summary else "",
            *(interface.suffix or "" for interface in interfaces),
        ]
    )
    gateways = _default_gateways(routes, interfaces)
    if not gateways:
        notes.append("no source reported a default gateway")
    if not dns:
        notes.append("no source reported a DNS server")

    return NetworkView(
        system="Windows",
        interface_source="ipconfig /all" if interfaces else None,
        interfaces=interfaces,
        routes=tuple(routes),
        gateways=tuple(gateways),
        dns=dns,
        resolution=tuple(_windows_resolution(hosts, summary, suffixes, dns)),
        hosts=hosts,
        suffixes=tuple(suffixes),
        tools=tuple(tools),
        notes=tuple(notes),
    )


def _posix_resolution(
    hosts: HostsFile, order: Sequence[str], dns: Sequence[DnsServer]
) -> list[ResolutionStep]:
    """With nsswitch.conf the order is read; without it only the hosts file is claimed."""
    if not order:
        return [
            ResolutionStep(
                1,
                "hosts file",
                (
                    f"{hosts.path} with {hosts.mappings} static entries"
                    if hosts.mappings is not None
                    else f"{hosts.path} ({hosts.note or 'unavailable'})"
                ),
                "file read directly",
            )
        ]
    details = {
        "files": hosts.path,
        "dns": ", ".join(server.address for server in dns) or "no nameserver reported",
        "myhostname": "answered by the resolver library itself",
        "mdns": "answered by mDNSResponder",
        "resolve": "answered by systemd-resolved",
        "nis": "answered by NIS",
    }
    return [
        ResolutionStep(
            position=index,
            label=source,
            detail=details.get(source, "order read from nsswitch.conf; no further detail"),
            evidence="/etc/nsswitch.conf hosts:",
        )
        for index, source in enumerate(order, start=1)
    ]


def _collect_posix(system: str, notes: list[str], tools: list[ToolResult]) -> NetworkView:
    interfaces: tuple[Interface, ...] = ()
    routes: list[Route] = []
    source: str | None = None

    if shutil.which("ip"):
        address_tool = run_tool(("ip", "addr", "show"))
        tools.append(address_tool)
        if address_tool.usable:
            interfaces = tuple(parse_ip_addr(address_tool.text or ""))
            source = "ip addr"
        else:
            notes.append(f"ip addr: {address_tool.note or 'no output'}")
        route4 = run_tool(("ip", "route", "show"))
        tools.append(route4)
        if route4.usable:
            routes += parse_ip_route(route4.text or "")
        else:
            notes.append(f"ip route: {route4.note or 'no output'}")
        route6 = run_tool(("ip", "-6", "route", "show"))
        tools.append(route6)
        if route6.usable:
            routes += parse_ip_route(route6.text or "")
        else:
            notes.append(f"ip -6 route: {route6.note or 'no output'} (IPv6 may be disabled)")
    else:
        notes.append("ip is not installed here, so the tool falls back to ifconfig")
        legacy = run_tool(("ifconfig", "-a"))
        tools.append(legacy)
        if legacy.usable:
            interfaces = tuple(parse_ifconfig(legacy.text or ""))
            source = "ifconfig -a"
        else:
            notes.append(
                f"ifconfig: {legacy.note or 'no output'} - neither ip nor ifconfig could "
                "be read, so the interface list is empty and reported as such"
            )
        if shutil.which("route"):
            single = run_tool(("route", "-n", "get", "default"))
            tools.append(single)
            if single.usable:
                routes += parse_route_get_default(single.text or "")
            table = run_tool(("route", "-n"))
            tools.append(table)
            if table.usable:
                routes += parse_route_n(table.text or "")
            if not routes:
                detail = single.note or table.note or "no output"
                notes.append(f"route produced nothing usable: {detail}")
        else:
            notes.append("neither ip nor route is available, so no default gateway can be read")

    servers: list[str] = []
    search: list[str] = []
    resolv_path = Path("/etc/resolv.conf")
    text, problem = read_text_file(resolv_path)
    if text is None:
        notes.append(f"{resolv_path}: {problem}")
    else:
        servers, search = parse_resolv_conf(text)
        if not servers:
            notes.append(f"{resolv_path} lists no nameserver (a stub resolver may own it)")

    hosts = read_hosts_file()
    if hosts.mappings is None:
        notes.append(f"hosts file: {hosts.note or 'unreadable'}")
    nsswitch_path = Path("/etc/nsswitch.conf")
    nsswitch_text, nsswitch_problem = read_text_file(nsswitch_path)
    order = parse_nsswitch_hosts(nsswitch_text) if nsswitch_text else []
    if not order:
        notes.append(
            f"nsswitch hosts order unavailable ({nsswitch_problem or 'no hosts: line'}), so "
            "the resolution order below is only what could be read locally"
        )

    from_resolv = [DnsServer(address, str(resolv_path)) for address in servers]
    dns = _dedupe_dns([*_dns_from_interfaces(interfaces), *from_resolv])
    gateways = _default_gateways(routes, interfaces)
    if not gateways:
        notes.append("no source reported a default gateway")
    if not dns:
        notes.append("no source reported a DNS server")

    return NetworkView(
        system=system,
        interface_source=source,
        interfaces=interfaces,
        routes=tuple(routes),
        gateways=tuple(gateways),
        dns=dns,
        resolution=tuple(_posix_resolution(hosts, order, dns)),
        hosts=hosts,
        suffixes=tuple(_dedupe(search)),
        tools=tuple(tools),
        notes=tuple(notes),
    )


def collect_network() -> NetworkView:
    """This machine's network configuration, read locally and never guessed."""
    notes: list[str] = []
    tools: list[ToolResult] = []
    system = platform.system()
    if system == "Windows":
        return _collect_windows(notes, tools)
    if os.name == "posix":
        return _collect_posix(system or "POSIX", notes, tools)
    notes.append(
        f"no reader is implemented for {system or 'this platform'}, so nothing is reported"
    )
    return NetworkView(
        system=system or "unknown",
        interface_source=None,
        interfaces=(),
        routes=(),
        gateways=(),
        dns=(),
        resolution=(),
        hosts=read_hosts_file(),
        suffixes=(),
        tools=tuple(tools),
        notes=tuple(notes),
    )


def describe_tool(result: ToolResult) -> str:
    """One honest line about a helper program."""
    if not result.available:
        return result.note or f"{result.argv[0]} is not available"
    if result.usable:
        return f"{result.argv[0]} ran from {result.path}"
    return f"{result.argv[0]} ran from {result.path}: {result.note or 'no parsable output'}"

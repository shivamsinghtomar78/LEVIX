"""The hacker module: rain, parsers and the command surface.

The parsers are tested against captured text rather than against a live system, so the
expected values below are known-correct by construction. The commands that read the
machine they run on are marked `integration` and assert only properties that hold on
every platform.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from levix.errors import EXIT_USAGE
from levix.module import Permission
from levix.modules.hacker import MANIFEST, core

# ----------------------------------------------------------------------------------
# Captured tool output
# ----------------------------------------------------------------------------------

IPCONFIG_ALL = """
Windows IP Configuration

   Host Name . . . . . . . . . . . . : WORKSTATION
   Primary Dns Suffix  . . . . . . . : lab.example
   Node Type . . . . . . . . . . . . : Hybrid
   IP Routing Enabled. . . . . . . . : No
   WINS Proxy Enabled. . . . . . . . : No

Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . : hgu.local
   Description . . . . . . . . . . . : Example AC1200 Wireless NIC
   Physical Address. . . . . . . . . : 3C-55-76-CE-A4-6B
   DHCP Enabled. . . . . . . . . . . : Yes
   Autoconfiguration Enabled . . . . : Yes
   Link-local IPv6 Address . . . . . : fe80::e81b:74:3a6c:940f%10(Preferred)
   IPv4 Address. . . . . . . . . . . : 192.168.87.4(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Lease Obtained. . . . . . . . . . : 03 November 2026 22:17:55
   Lease Expires . . . . . . . . . . : 04 November 2026 22:17:56
   Default Gateway . . . . . . . . . : 192.168.87.1
   DHCP Server . . . . . . . . . . . : 192.168.87.1
   DNS Servers . . . . . . . . . . . : 103.107.9.6
                                       103.155.73.14
   NetBIOS over Tcpip. . . . . . . . : Enabled

Ethernet adapter vEthernet (WSL):

   Connection-specific DNS Suffix  . :
   Description . . . . . . . . . . . : Hyper-V Virtual Ethernet Adapter
   Physical Address. . . . . . . . . : 00-15-5D-39-F8-04
   DHCP Enabled. . . . . . . . . . . : No
   Autoconfiguration Enabled . . . . : Yes
   IPv4 Address. . . . . . . . . . . : 172.28.208.1(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.240.0
   Default Gateway . . . . . . . . . :
   NetBIOS over Tcpip. . . . . . . . : Enabled

Wireless LAN adapter Local Area Connection* 3:

   Media State . . . . . . . . . . . : Media disconnected
   Connection-specific DNS Suffix  . :
   Description . . . . . . . . . . . : Microsoft Wi-Fi Direct Virtual Adapter
   Physical Address. . . . . . . . . : 3E-55-76-CE-A4-6B
   DHCP Enabled. . . . . . . . . . . : Yes
   Autoconfiguration Enabled . . . . : Yes
"""

ROUTE_PRINT = """
===========================================================================
Interface List
 10...3c 55 76 ce a4 6b ......Example AC1200 Wireless NIC
  1...........................Software Loopback Interface 1
 44...00 15 5d 39 f8 04 ......Hyper-V Virtual Ethernet Adapter
===========================================================================

IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0     192.168.87.1     192.168.87.4     35
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
        172.28.208.0        255.255.240.0         On-link      172.28.208.1   256
===========================================================================
Persistent Routes:
  None

IPv6 Route Table
===========================================================================
Active Routes:
  None
Persistent Routes:
  None
"""

IP_ADDR_SHOW = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
4: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
    inet 10.0.0.42/24 brd 10.0.0.255 scope global dynamic noprefixroute wlan0
       valid_lft 3582sec preferred_lft 3582sec
    inet6 fe80::1c2d:3eff:fe4d:5a6b/64 scope link
       valid_lft forever preferred_lft forever
5: veth0@if7: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
    link/ether 02:42:ac:11:00:02 brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 brd 172.17.255.255 scope global veth0
"""

IP_ROUTE_SHOW = """
default via 10.0.0.1 dev wlan0 proto dhcp src 10.0.0.42 metric 600
10.0.0.0/24 dev wlan0 proto kernel scope link src 10.0.0.42 metric 300
172.17.0.0/16 dev veth0 proto kernel scope link src 172.17.0.1 metric 303
"""

IFCONFIG_SHOW = """
lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        inet6 ::1  prefixlen 128  scopeid 0x10<host>
        loop  txqueuelen 1000  (Local Loopback)

en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        ether a4:83:e7:11:22:33
        inet 192.168.1.30 netmask 0xffffff00 broadcast 192.168.1.255
        inet6 fe80::1a2b:3c4d:5e6f:7a8b%en0 prefixlen 64 secured scopeid 0x6
        media: autoselect
        status: active
"""

RESOLV_CONF = """
# generated by NetworkManager
nameserver 192.168.1.1
nameserver 2001:4860:4860::8888
search lab.example home
options edns0
"""

NSSWITCH_CONF = """
passwd:      files sss
group:       files sss
hosts:       files mdns4_minimal [NOTFOUND=return] dns
networks:    files dns
"""

ROUTE_N_SHOW = """
Kernel IP routing table
Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
0.0.0.0         10.0.0.1        0.0.0.0         UG    600    0        0 wlan0
10.0.0.0        0.0.0.0         255.255.255.0   U     300    0        0 wlan0
"""

ROUTE_GET_DEFAULT = """
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING>
 recvpipe  sendpipe  ssthresh  rtt,msec    rtttime    mtu     age
      0         0         0         0         0         0      43
"""

# ----------------------------------------------------------------------------------
# Matrix rain
# ----------------------------------------------------------------------------------


def _scene(seed=11, columns=24, rows=10, density=0.25, **kwargs):
    return core.MatrixScene(columns=columns, rows=rows, density=density, seed=seed, **kwargs)


def test_seeded_scene_repeats_every_frame_exactly():
    first = core.run_frames(_scene(seed=42), 8)
    second = core.run_frames(_scene(seed=42), 8)
    assert [frame.rows for frame in first] == [frame.rows for frame in second]
    assert [frame.levels for frame in first] == [frame.levels for frame in second]


def test_different_seeds_give_different_rain():
    a = core.run_frames(_scene(seed=1), 6)
    b = core.run_frames(_scene(seed=2), 6)
    assert [frame.rows for frame in a] != [frame.rows for frame in b]


def test_frame_geometry_is_the_requested_grid_and_charset():
    frame = _scene(seed=3).tick()
    assert frame.height == 10
    assert frame.width == 24
    assert all(len(line) == 24 for line in frame.rows)
    assert all(len(line) == 24 for line in frame.levels)
    allowed = set(core.RAIN_CHARS) | {"#", "+", " "}
    assert set("".join(frame.rows)) <= allowed
    assert {level for line in frame.levels for level in line} <= {
        core.BLANK,
        core.FAINT,
        core.TAIL,
        core.NEAR,
        core.HEAD,
    }


def test_a_fresh_scene_has_no_drops_until_the_first_frame():
    scene = core.MatrixScene(columns=6, rows=4, density=0.001, seed=5)
    assert scene.active_columns == 0
    assert scene.tick().width == 6
    assert scene.tick().height == 4


def test_rain_builds_up_over_time_for_a_fixed_seed():
    frames = core.run_frames(_scene(seed=7, density=0.1), 20)
    assert frames[-1].lit_cells > frames[0].lit_cells


def test_higher_density_lights_more_cells():
    sparse = sum(frame.lit_cells for frame in core.run_frames(_scene(seed=9, density=0.02), 12))
    thick = sum(frame.lit_cells for frame in core.run_frames(_scene(seed=9, density=0.5), 12))
    assert thick > sparse


def test_head_is_always_the_given_head_character():
    scene = _scene(seed=21, density=1.0, head_char="@", near_char="-")
    scene.tick()
    frame = scene.tick()
    assert core.HEAD in {level for line in frame.levels for level in line}
    for chars, levels in zip(frame.rows, frame.levels, strict=True):
        for char, level in zip(chars, levels, strict=True):
            if level == core.HEAD:
                assert char == "@"
            if level == core.NEAR:
                assert char == "-"


def test_priming_starts_with_rain_already_falling():
    scene = core.MatrixScene(columns=60, rows=20, density=0.05, seed=31)
    assert scene.active_columns == 0
    scene.prime()
    assert scene.active_columns > 0
    assert scene.tick().lit_cells > 0


def test_primed_scene_is_deterministic_too():
    first = core.MatrixScene(columns=40, rows=12, density=0.05, seed=77)
    second = core.MatrixScene(columns=40, rows=12, density=0.05, seed=77)
    first.prime()
    second.prime()
    assert core.run_frames(first, 5) == core.run_frames(second, 5)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"columns": 0, "rows": 10, "density": 0.1}, "at least one cell"),
        ({"columns": 10, "rows": 0, "density": 0.1}, "at least one cell"),
        ({"columns": 10, "rows": 10, "density": 0.0}, "greater than 0"),
        ({"columns": 10, "rows": 10, "density": 1.5}, "at most 1"),
        ({"columns": 10, "rows": 10, "density": 0.1, "head_char": "ab"}, "one cell wide"),
    ],
)
def test_impossible_rain_configurations_are_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        core.MatrixScene(**kwargs)


def test_unprimed_scene_reaches_the_bottom_and_resets():
    scene = core.MatrixScene(columns=1, rows=3, density=1.0, seed=1)
    for _ in range(40):
        scene.tick()
    assert 0 <= scene.active_columns <= 1


# ----------------------------------------------------------------------------------
# Value normalisation
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3C-55-76-CE-A4-6B", "3C:55:76:CE:A4:6B"),
        ("3c:55:76:ce:a4:6b", "3C:55:76:CE:A4:6B"),
        ("3c55.76ce.a46b", "3C:55:76:CE:A4:6B"),
        ("00 15 5d 39 f8 04", "00:15:5D:39:F8:04"),
        ("", None),
        ("3C-55-76-CE-A4", None),
        ("not a mac at all", None),
    ],
)
def test_mac_addresses_are_normalised_or_dropped(raw, expected):
    assert core.normalise_mac(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("255.255.255.0", "24"),
        ("255.255.240.0", "20"),
        ("255.0.0.0", "8"),
        ("0xffffff00", "24"),
        ("24", "24"),
        ("255.255.255.1", "255.255.255.1"),
        (None, None),
        ("", None),
    ],
)
def test_netmasks_become_cidr_lengths(raw, expected):
    assert core.normalise_prefix(raw) == expected


@pytest.mark.parametrize(
    ("value", "family"),
    [
        ("192.168.87.4", "ipv4"),
        ("fe80::e81b:74:3a6c:940f%10", "ipv6"),
        ("::1", "ipv6"),
        ("2001:4860:4860::8888", "ipv6"),
        ("10.0.0.42/24", "ipv4"),
        ("Media disconnected", "other"),
        ("300", "other"),
        ("192.168.1.999", "other"),
    ],
)
def test_address_shapes_are_recognised_and_prose_is_not(value, family):
    assert core.address_family(value) == family


def test_dot_leaders_and_colons_inside_values_survive_the_key_split():
    key, value = core.split_key_line("   Lease Obtained. . . . : 03 November 2026 22:17:55")
    assert key == "leaseobtained"
    assert value == "03 November 2026 22:17:55"
    assert core.split_key_line("Windows IP Configuration") is None


def test_ipconfig_style_annotations_are_stripped():
    assert core.strip_annotation("192.168.87.4(Preferred)") == "192.168.87.4"
    assert core.strip_annotation("fe80::1%10(Temporary)") == "fe80::1%10"
    assert core.strip_annotation("103.107.9.6") == "103.107.9.6"
    # Only the annotations ipconfig actually prints are removed; anything else stays,
    # because guessing what a stranger in brackets meant is how bad data is born.
    assert core.strip_annotation("103.107.9.6 (lab router)") == "103.107.9.6 (lab router)"


# ----------------------------------------------------------------------------------
# Windows parsers
# ----------------------------------------------------------------------------------


def test_ipconfig_all_yields_the_adapters_that_were_printed():
    summary = core.parse_ipconfig_all(IPCONFIG_ALL)
    assert [interface.name for interface in summary.interfaces] == [
        "Wi-Fi",
        "vEthernet (WSL)",
        "Local Area Connection* 3",
    ]
    assert summary.hostname == "WORKSTATION"
    assert summary.primary_dns_suffix == "lab.example"
    assert summary.node_type == "Hybrid"
    assert summary.ip_routing is False
    assert summary.wins_proxy is False


def test_ipconfig_adapter_fields_are_read_not_invented():
    wifi = core.parse_ipconfig_all(IPCONFIG_ALL).interfaces[0]
    assert wifi.kind == "Wireless LAN"
    assert wifi.description == "Example AC1200 Wireless NIC"
    assert wifi.mac == "3C:55:76:CE:A4:6B"
    assert wifi.dhcp is True
    assert wifi.gateway == "192.168.87.1"
    assert wifi.suffix == "hgu.local"
    assert wifi.netbios == "Enabled"
    assert wifi.state is None
    assert [(item.address, item.kind, item.prefix) for item in wifi.addresses] == [
        ("192.168.87.4", "configured", "24"),
        ("fe80::e81b:74:3a6c:940f%10", "link-local", None),
    ]


def test_continuation_lines_are_a_second_dns_server():
    wifi = core.parse_ipconfig_all(IPCONFIG_ALL).interfaces[0]
    assert wifi.dns == ("103.107.9.6", "103.155.73.14")


def test_an_empty_gateway_and_a_disconnected_adapter_stay_unreported():
    summary = core.parse_ipconfig_all(IPCONFIG_ALL)
    wsl = summary.interfaces[1]
    assert wsl.gateway is None
    assert wsl.dhcp is False
    assert wsl.dns == ()
    assert wsl.mac == "00:15:5D:39:F8:04"
    disconnected = summary.interfaces[2]
    assert disconnected.state == "disconnected"
    assert disconnected.addresses == ()
    assert disconnected.reported_state == "disconnected"


def test_ipconfig_output_without_adapter_sections_parses_as_nothing():
    summary = core.parse_ipconfig_all("Server IP Configuration\n\n   Blah . . . : 1\n")
    assert summary.interfaces == ()
    assert summary.hostname is None


def test_route_print_default_route_keeps_metric_and_gateway():
    routes = core.parse_route_print(ROUTE_PRINT)
    assert [route.destination for route in routes] == [core.ANY_IPV4, "127.0.0.0", "172.28.208.0"]
    default = routes[0]
    assert default.is_default
    assert default.gateway == "192.168.87.1"
    assert default.interface == "192.168.87.4"
    assert default.metric == 35
    assert default.source == "route print"


def test_route_print_on_link_rows_are_not_reported_as_gateways():
    routes = core.parse_route_print(ROUTE_PRINT)
    loopback = routes[1]
    assert loopback.gateway is None
    assert not loopback.is_default


def test_gateway_selection_prefers_the_route_table_then_per_adapter():
    summary = core.parse_ipconfig_all(IPCONFIG_ALL)
    routes = core.parse_route_print(ROUTE_PRINT)
    gateways = core._default_gateways(routes, summary.interfaces)
    assert gateways[0].source == "route print"
    assert gateways[0].address == "192.168.87.1"
    assert not gateways[0].on_link
    assert not any(gateway.address == "" for gateway in gateways)


def test_gateway_selection_marks_an_on_link_default_honestly():
    routes = core.parse_route_print(
        "IPv4 Route Table\nActive Routes:\n"
        "          0.0.0.0          0.0.0.0         0.0.0.0      10.0.0.5      20\n"
    )
    gateways = core._default_gateways(routes, [])
    assert len(gateways) == 1
    assert gateways[0].on_link
    assert gateways[0].address is None
    assert gateways[0].reported == "directly connected on 10.0.0.5"


def test_gateway_selection_falls_back_to_the_adapter_value():
    wifi = core.parse_ipconfig_all(IPCONFIG_ALL).interfaces[0]
    gateways = core._default_gateways([], [wifi])
    assert len(gateways) == 1
    assert gateways[0].address == "192.168.87.1"
    assert gateways[0].source == "ipconfig /all (per interface)"


def test_route_print_with_no_table_produces_no_routes():
    assert core.parse_route_print("IPv4 Route Table\nActive Routes:\n  None\n") == []


# ----------------------------------------------------------------------------------
# POSIX parsers
# ----------------------------------------------------------------------------------


def test_ip_addr_show_lists_interfaces_addresses_and_flags():
    interfaces = core.parse_ip_addr(IP_ADDR_SHOW)
    assert [interface.name for interface in interfaces] == ["lo", "wlan0", "veth0"]
    loopback, wlan, veth = interfaces
    assert loopback.is_loopback
    assert wlan.mac == "AA:BB:CC:DD:EE:FF"
    assert wlan.state == "up"
    assert [(item.address, item.prefix) for item in wlan.addresses] == [
        ("10.0.0.42", "24"),
        # `ip addr` prints the link-local v6 address with its /64, so the prefix here is
        # read from the same column rather than assumed.
        ("fe80::1c2d:3eff:fe4d:5a6b", "64"),
    ]
    assert veth.kind is None
    assert veth.addresses[0].address == "172.17.0.1"
    # The loopback has no `link/ether` line, so no MAC is reported for it.
    assert loopback.mac is None


def test_ip_addr_link_local_v6_is_labelled_as_such():
    wlan = core.parse_ip_addr(IP_ADDR_SHOW)[1]
    kinds = {item.kind for item in wlan.addresses}
    assert kinds == {"configured", "link-local"}


def test_ip_route_default_gateway_metric_and_device():
    routes = core.parse_ip_route(IP_ROUTE_SHOW)
    assert [route.destination for route in routes] == ["default", "10.0.0.0", "172.17.0.0"]
    default = routes[0]
    assert default.gateway == "10.0.0.1"
    assert default.interface == "wlan0"
    assert default.metric == 600
    assert default.is_default
    assert not routes[1].is_default


def test_ifconfig_handles_both_net_tools_and_macos_shapes():
    interfaces = core.parse_ifconfig(IFCONFIG_SHOW)
    assert [interface.name for interface in interfaces] == ["lo", "en0"]
    lo, en0 = interfaces
    assert lo.is_loopback
    assert lo.addresses[0].prefix == "8"
    assert en0.mac == "A4:83:E7:11:22:33"
    assert en0.addresses[0].address == "192.168.1.30"
    assert en0.addresses[0].prefix == "24"
    # ifconfig has no `state` word the way `ip addr` does, so the interface flags are
    # what the state is read from. The flag list is kept alongside the up/down reading
    # instead of being thrown away, and nothing here is invented.
    assert en0.state == "up (UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST)"
    assert en0.reported_state == "up (UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST)"


def test_route_n_and_route_get_default_are_both_parsable():
    linux = core.parse_route_n(ROUTE_N_SHOW)
    assert linux[0].destination == core.ANY_IPV4
    assert linux[0].gateway == "10.0.0.1"
    assert linux[0].interface == "wlan0"
    assert linux[0].metric == 600
    assert linux[0].is_default
    # The directly-connected row prints 0.0.0.0 as its gateway; that is "no hop", not
    # an address, and the on-link row must not be reported as a gateway either.
    assert linux[1].gateway is None

    bsd = core.parse_route_get_default(ROUTE_GET_DEFAULT)
    assert len(bsd) == 1
    assert bsd[0].gateway == "192.168.1.1"
    assert bsd[0].interface == "en0"

    assert core.parse_route_get_default("nothing useful here") == []


def test_resolv_conf_orders_nameservers_and_keeps_search_domains():
    servers, search = core.parse_resolv_conf(RESOLV_CONF)
    assert servers == ["192.168.1.1", "2001:4860:4860::8888"]
    assert search == ["lab.example", "home"]


def test_nsswitch_hosts_line_is_the_resolution_order():
    assert core.parse_nsswitch_hosts(NSSWITCH_CONF) == [
        "files",
        "mdns4_minimal",
        "dns",
    ]
    assert core.parse_nsswitch_hosts("passwd: files\n") == []


# ----------------------------------------------------------------------------------
# Host facts and file reads
# ----------------------------------------------------------------------------------


def test_host_facts_match_the_stdlib_they_derive_from():
    import os
    import platform
    import socket

    facts = core.host_facts()
    assert facts.hostname == socket.gethostname()
    assert facts.system == platform.system()
    assert facts.machine == platform.machine()
    assert facts.python_version == platform.python_version()
    assert facts.pid == os.getpid()
    assert facts.cpu_count == os.cpu_count()
    assert facts.terminal.encoding == (sys.stdout.encoding or facts.terminal.encoding)
    assert facts.user


def test_hosts_file_reports_what_it_found_without_raising(tmp_path):
    present = tmp_path / "hosts"
    present.write_text("# comment only\n\n127.0.0.1 localhost\n", encoding="utf-8")
    assert core.read_hosts_file(present).mappings == 1

    missing = core.read_hosts_file(tmp_path / "nope")
    assert not missing.exists
    assert missing.mappings is None
    assert "does not exist" in missing.note


def test_read_text_file_reports_a_problem_instead_of_raising(tmp_path):
    text, problem = core.read_text_file(tmp_path / "absent.conf")
    assert text is None
    assert "absent.conf" in problem


def test_run_tool_reports_a_program_that_is_not_installed():
    result = core.run_tool(("definitely-not-a-real-program-9000", "--version"))
    assert not result.available
    assert not result.usable
    assert "not on PATH" in result.note


def test_run_tool_runs_an_argument_list_not_a_shell():
    marker = "ipconfig" if sys.platform.startswith("win") else "sh"
    flag = "/not-a-real-flag" if marker == "ipconfig" else "--no-such-flag"
    result = core.run_tool((marker, flag))
    assert result.available
    assert result.path is not None and Path(result.path).is_absolute()
    assert result.returncode is not None
    assert not result.usable or result.text


# ----------------------------------------------------------------------------------
# Lazy loading and the manifest
# ----------------------------------------------------------------------------------


def test_importing_the_module_package_pulls_in_no_heavy_dependency():
    code = (
        "import sys\n"
        "import levix.modules.hacker as h\n"
        "heavy = [m for m in ('psutil', 'yt_dlp', 'sounddevice', 'soundfile', 'rich', "
        "'typer', 'textual', 'httpx') if m in sys.modules]\n"
        "print(len(h.MANIFEST.commands), heavy)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "3 []"


def test_manifest_declares_the_packaged_contract():
    assert MANIFEST.name == "hacker"
    assert MANIFEST.cli_path == "levix.modules.hacker.cli:build_app"
    assert MANIFEST.command_names() == ("matrix", "info", "network")
    assert MANIFEST.requirements == ()
    assert MANIFEST.extras == ()
    assert MANIFEST.ui is not None
    assert MANIFEST.ui.mode == "suspend"
    assert MANIFEST.ui.argv == ("hacker", "matrix")
    assert MANIFEST.documentation == "docs/modules/HACKER.md"
    assert Permission.SUBPROCESS in MANIFEST.permissions
    assert Permission.FS_READ in MANIFEST.permissions
    assert Permission.NETWORK not in MANIFEST.permissions


# ----------------------------------------------------------------------------------
# Command surface
# ----------------------------------------------------------------------------------


def test_help_lists_all_three_commands(run_cli, capsys):
    assert run_cli("hacker", "-h") == 0
    text = capsys.readouterr().out
    for name in MANIFEST.command_names():
        assert name in text


def test_info_prints_this_machine_and_exits_cleanly(run_cli, capsys):
    import socket

    assert run_cli("hacker", "info") == 0
    text = capsys.readouterr().out
    assert socket.gethostname() in text
    assert "Hacker / this machine" in text
    assert "Interpreter" in text
    assert "Terminal" in text
    assert "Local interfaces" in text
    assert "Traceback" not in text


#: What CI's macOS runner calls itself: 68 characters, wider than the value column the
#: host table can afford inside the 80 columns a captured stdout implies.
LONG_HOSTNAME = "iad20-gt1018-b2808a49-24f5-4b35-a580-e30f8dc8023e-C64BF1B94850.local"


def test_a_hostname_longer_than_the_table_stays_in_one_piece(run_cli, capsys, monkeypatch):
    """The machine's name is the one value here a user copies out of the terminal.

    `test_info_prints_this_machine_and_exits_cleanly` prints whatever this box is called,
    and a short name never exposes the layout. This is the same assertion against the
    width that split the runner's name mid-token in CI run #3.
    """
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: LONG_HOSTNAME)
    assert run_cli("hacker", "info") == 0
    assert LONG_HOSTNAME in capsys.readouterr().out


def _view(**overrides: object) -> core.NetworkView:
    """A NetworkView with nothing collected, so one field can be rendered on its own."""
    base: dict[str, object] = {
        "system": "TestOS",
        "interface_source": None,
        "interfaces": (),
        "routes": (),
        "gateways": (),
        "dns": (),
        "resolution": (),
        "hosts": None,
        "suffixes": (),
        "tools": (),
        "notes": (),
    }
    base.update(overrides)
    return core.NetworkView(**base)


def test_the_tools_table_keeps_the_error_the_os_actually_reported(capsys):
    """A Windows explanation starts `[WinError 2] `, a POSIX one `[Errno 2] `.

    Rich parses a bare `[...]` as a style tag and deletes it, so the detail column used to
    print "could not run ipconfig: The system cannot find the file specified" - the sentence
    with its error code removed. This table exists to name what went wrong.
    """
    from levix.modules.hacker import cli

    note = "could not run ipconfig: [WinError 2] The system cannot find the file specified"
    cli._report_sources(_view(tools=(core.ToolResult.unavailable(["ipconfig", "/all"], note),)))
    printed = " ".join(capsys.readouterr().out.split())
    assert "[WinError 2]" in printed, "the error number was consumed as markup"
    assert "ipconfig /all" in printed


def test_a_field_that_looks_like_a_closing_tag_does_not_kill_the_report():
    """`[/x]` is not deleted by Rich: it raises MarkupError while the table renders.

    A single stray close tag in a name this module never chose would turn `levix hacker
    network` into a traceback, so the escaping is not cosmetic.
    """
    from rich.console import Console

    from levix.modules.hacker import cli

    view = _view(dns=(core.DnsServer(address="10.0.0.[/7]", source="resolv.conf"),))
    console = Console(record=True, width=120, color_system=None)
    console.print(cli._dns_table(view))
    assert "10.0.0.[/7]" in " ".join(console.export_text().split())


def test_matrix_stops_at_the_frame_limit(run_cli, capsys):
    assert run_cli("hacker", "matrix", "--iterations", "2", "--fps", "60") == 0
    text = capsys.readouterr().out
    assert "2 frames at 60 fps" in text


def test_matrix_stops_at_the_time_limit(run_cli, capsys):
    assert run_cli("hacker", "matrix", "--duration", "0.2", "--fps", "20") == 0
    assert "stopped by --duration" in capsys.readouterr().out


def test_matrix_seed_repeats_a_run(run_cli, capsys):
    assert run_cli("hacker", "matrix", "--iterations", "4", "--seed", "5", "--width", "30") == 0
    first = capsys.readouterr().out
    assert run_cli("hacker", "matrix", "--iterations", "4", "--seed", "5", "--width", "30") == 0
    assert capsys.readouterr().out == first


def test_matrix_needs_a_bound_when_stdout_is_captured(run_cli, capsys):
    assert run_cli("hacker", "matrix", "--duration", "0", "--iterations", "0") == EXIT_USAGE
    text = capsys.readouterr()
    assert "not a terminal" in text.err or "not a terminal" in text.out
    assert "Traceback" not in text.err


@pytest.mark.parametrize(("flag", "value"), [("--fps", "500"), ("--fps", "-2"), ("--density", "3")])
def test_out_of_range_effect_settings_are_usage_errors(run_cli, flag, value):
    assert run_cli("hacker", "matrix", flag, value, "--iterations", "1") == EXIT_USAGE


@pytest.mark.integration
def test_network_reports_real_local_configuration(run_cli, capsys):
    assert run_cli("hacker", "network") == 0
    text = capsys.readouterr().out
    assert "Default gateway" in text
    assert "DNS servers" in text
    assert "Hostname resolution order" in text
    assert "Where the data came from" in text
    assert "Traceback" not in text


@pytest.mark.integration
def test_network_never_shows_a_placeholder_gateway(run_cli, capsys):
    assert run_cli("hacker", "network") == 0
    text = capsys.readouterr().out
    # 0.0.0.0 is only allowed where the route table genuinely contains it, never as a
    # stand-in for "we could not read anything".
    gateway_block = text.split("Default gateway", 1)[-1].split("DNS servers", 1)[0]
    if "not available on this platform" not in gateway_block:
        assert "0.0.0.0 " not in gateway_block

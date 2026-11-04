# ADR-0006 - One distribution, optional extras, and a gate that refuses before importing

Status: accepted
Date: 2026-11-04

## Context

Seven modules, one of which shells out to a media site's Python client, one of which needs
PortAudio, one of which needs psutil. A user who only wants Snake should not have to
install audio drivers, and a user who types `levix tube` without yt-dlp should get a
sentence they can act on, not a traceback.

| Option | Why it was not chosen |
| --- | --- |
| Everything in `dependencies` | The core stops being lightweight on the first `pip install`; a WAV-only user gets PortAudio |
| One distribution per module (`levix-tube`, …) | Seven release pipelines, seven version matrices, and "install LEVIX" stops having one answer |
| `try: import yt_dlp / except ImportError: print("not installed")` in each command | Imports a heavy module to decide whether to import it, gives eight slightly different error messages, and cannot be reported by `levix doctor` |
| Auto-`pip install` on first use | Installs arbitrary code into the user's environment from a command that looked like a question. Never |
| Extras + one gate in front of each module | What shipped |

## Decision

`pyproject.toml` declares core dependencies and one extra per module that needs anything:

```toml
[project.optional-dependencies]
monitor = ["psutil>=7.2,<8"]
tube = ["yt-dlp>=2026.10.26"]
music = ["sounddevice>=0.5,<1", "soundfile>=0.14,<1", "numpy>=2.0,<3"]
ai = ["httpx>=0.28,<1"]
secrets = ["keyring>=25.7,<26"]
```

Each manifest then names what it needs twice, in different currencies: `requirements` is
the *probe* (`PackageRef(import_name, dist_name, minimum)`) and `extras` is the *remedy*
(`pip install "levix[tube]"`). They are separate fields because an import name and a
distribution name differ (`yt_dlp` vs `yt-dlp`), and one field would produce a hint that
cannot work.

`deps.ensure_dependencies(MANIFEST)` runs from each module's own Typer callback:

```python
def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    ensure_dependencies(MANIFEST)
```

so `levix tube -h` works with yt-dlp missing and `levix tube search` does not. The gate
raises `DependencyError` (exit 3) naming every unsatisfied package and the exact install
line. Availability comes from `importlib.util.find_spec` plus `importlib.metadata`, never
from an import, and version comparison is a nine-line numeric-prefix rule rather than
`packaging`, because four pins do not justify a permanent core dependency. A version that
cannot be parsed is reported as `UNCERTAIN`, not accepted silently.

Files, Hacker, Arcade and Music-on-a-quiet-disk declare no requirements at all: those
modules are stdlib plus Rich/Textual, which the core already has.

## Consequences

- The lightweight-core claim is checkable in the built artifact rather than argued. The
  `levix-0.4.0-py3-none-any.whl` built by this repository lists exactly six unconditional
  `Requires-Dist` entries - `click`, `platformdirs`, `rich`, `textual`, `tomlkit`, `typer` -
  and every one of `httpx`, `keyring`, `numpy`, `psutil`, `sounddevice`, `soundfile` and
  `yt-dlp` carries `extra == '...'`.
- **`textual` is a core dependency and it is the heavy one.** The dashboard is a product
  feature, not an optional extra, so it is unconditional. The mitigation is runtime
  laziness, and it is verified rather than asserted: `tests/test_router.py` runs the real
  entry point in a child interpreter and fails if `textual` (or psutil, yt_dlp,
  sounddevice, soundfile, numpy) appears in `sys.modules` after `levix --help` or
  `levix tube -h`. What this ADR does *not* claim is a small install footprint - `pip
  install levix` does pull Textual and Rich.
- The gate is per module, not in the router, because the router cannot know whether the
  command being run is `-h`. The cost is that a plugin author has to remember to call it,
  and `deps.ensure_dependencies` is **not** re-exported from `levix.sdk` today. That is a
  contract hole, not a design choice, and it is listed in `docs/roadmap/CURRENT_STATUS.md`.
- Three states are reported, not two: `doctor` and the dashboard badges read the same
  `resolve()`, so "installed but older than the pin" (`TOO_OLD`) is distinguishable from
  "absent", and the install hint differs (`needs psutil 7.2`, you have 6).
- A module that declares no provider distribution cannot fabricate a hint:
  `resolved_install_hint()` returns `None` and the message says "no install hint is
  declared for this module" instead of printing `pip install "[tube]"`, which names no
  package.
- Nothing in this path installs, upgrades or removes anything. `levix update` checks for a
  newer version and prints the command; it does not run it.

## Verification

`tests/test_deps.py` - 17 cases, including the one that fails if availability is answered
by importing: the probe must never bring the probed module into `sys.modules`; `yt_dlp` →
`yt-dlp` naming in the reported hint; a multi-extra hint producing one distribution
(`levix[ai+secrets]`); the four availability states; and an unparseable installed version
reporting `UNCERTAIN`.
`tests/test_router.py` drives the gate through the real entry point: a stub module whose
requirement cannot be satisfied exits 3, its help still exits 0, and the printed message
contains no `pip install` line when no hint exists.
`tests/test_markup_safety.py` asserts the hint survives rendering - `levix[tube]` is
exactly the text Rich would otherwise delete.
`tests/test_plugin_example.py` proves a third-party distribution's own `provider` yields
its own install line rather than LEVIX's.

Not verified: a throwaway environment install of the built wheel with no extras (the
metadata above is the evidence in place of it), and any module run on a machine where the
extra is genuinely absent - `pip install levix` then `levix tube` has not been executed
here, because this venv has all extras installed.

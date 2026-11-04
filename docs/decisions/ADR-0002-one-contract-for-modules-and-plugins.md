# ADR-0002 - Official modules and third-party plugins share one contract

Status: accepted
Date: 2026-11-04

## Context

Tube, Hacker, SystemPulse, AI, Music, Arcade and Files live inside this repository. The
easiest design gives them a private path - a hard-coded list in the router, imports at
startup, a richer manifest class for "real" modules - and hands third parties a smaller,
second-rate API.

That is the arrangement that rots: the shipped modules get exercised, the plugin surface
does not, and the first external author discovers the gap.

## Decision

The seven official modules are plugins. Each lives at
`src/levix/modules/<name>/`, exposes a `MANIFEST` of the same `ModuleManifest` type a
third party uses, and registers through the same `levix.plugins` entry-point group in
`pyproject.toml`. There is exactly one loader (`registry.py`), one router path
(`router.py`), one dependency gate (`deps.py`) and one row builder for the dashboard
(`dashboard/module_list.py`).

`origin` and `provider` are stamped by the registry from the distribution that provided the
entry point, and are **never read from what the plugin claims**:

```python
provider = entry_point.dist.name if entry_point.dist else ""
origin = _origin_for(provider, manifest.name)   # OFFICIAL_DISTRIBUTION == "levix"
```

`OFFICIAL_NAMES` (`monitor`, `hacker`, `files`, `tube`, `game`, `music`, `ai`) is a second
guard, so a distribution named `levix` that is not this project still cannot rename its way
into an official row.

## Consequences

- Anything a plugin can do, the core has to do honestly. The example plugin
  (`plugin-examples/hello`) is a test fixture, so a contract break fails the suite instead
  of failing a stranger.
- A third party cannot present itself as official: `ModuleManifest(origin=...)` is
  overwritten at discovery, and `tests/test_registry.py` asserts an impostor manifest keeps
  `THIRD_PARTY` and its own declared version.
- Official modules are shipped with the CLI, so a manifest typo is a core release issue, not
  a user's bad install. The dashboard's rows and `levix plugins list` both read the
  registry, so the two views cannot disagree by construction.
- The shared contract has holes that are visible from the outside and recorded rather than
  papered over: `permissions` is a disclosure, not a sandbox; a plugin cannot add a
  configuration section because `config.SCHEMA` is owned by the core; and
  `deps.ensure_dependencies` is not re-exported from `levix.sdk`, so a plugin that declares
  `requirements` must call the gate from its own Typer callback the way the official modules
  do. Each is listed in `docs/roadmap/CURRENT_STATUS.md` as open work.

## Verification

`tests/test_registry.py` covers stamping, the impostor case and the version precedence
(`manifest.version or _dist_version(...)`). `tests/test_router.py` runs a stub module that
is not one of the seven, which is only possible because the router knows nothing about
official names. `tests/test_plugin_example.py` runs the example end to end.

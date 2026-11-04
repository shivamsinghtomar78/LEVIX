# ADR-0001 - Discovery is `importlib.metadata` entry points, not a scan

Status: accepted
Date: 2026-11-04

## Context

LEVIX has to find modules it has never heard of. The options on the table:

| Option | What it costs |
| --- | --- |
| Scan a `~/.config/levix/plugins/` folder for Python files | A second, non-standard install path; no version, no dependency metadata, no uninstall; a filename becomes an import name |
| A hand-maintained registry file (`plugins.json`) | LEVIX ships a list of third parties it does not control, and every install edits a file outside its own package |
| `pluggy` or another plugin framework | A real dependency whose only job here is name dispatch |
| `importlib.metadata.entry_points(group="levix.plugins")` | Zero dependencies, already how the packages users install are described |

The mission is "one CLI, multiple applications, unlimited extensibility", so discovery has
to work for whatever `pip`, `uv`, `conda` or a venv put on the machine, without LEVIX
inventing an installer of its own.

## Decision

A module registers by declaring one entry point in the group `levix.plugins`:

```toml
[project.entry-points."levix.plugins"]
hello = "levix_hello:MANIFEST"
```

`levix.registry.ModuleRegistry.discover()` reads that group, loads each target and keys the
result by `manifest.name`. The group name is the entire contract; there is no folder to
watch and no config key to edit. `ModuleRegistry(extra_entry_points=...)` exists so a test
can inject a registry without touching the filesystem, and `LEVIX_HOME`-based tests use it.

The official modules use the same mechanism - see `ADR-0002`.

## Consequences

- Installing a module is `pip install`. Uninstalling it is `pip uninstall`, and LEVIX needs
  no `plugins install` command to be correct (that command is planned; it will be a
  convenience over pip, not a second source of truth).
- Version, distribution name and dependency metadata come free from the installed
  distribution, which is what makes `provider`, `version` and the install hints in
  `deps.py` honest rather than guessed.
- A broken entry point must not make LEVIX unstartable. `discover()` catches every
  exception from `.load()` and records a `_broken(...)` manifest whose `cli_path` is empty;
  `is_broken` is `not manifest.cli_path`, and `levix plugins list` / `levix doctor` report
  the failure text (`ModuleNotFoundError`, "not ModuleManifest") while the healthy modules
  keep working. Running a broken module raises `DependencyError` with exit 3
  (`MISSING_DEPENDENCY`), never an `ImportError` traceback.
- Discovery is only as good as the distribution metadata. A standalone executable built by
  PyInstaller has to bundle `*.dist-info` for entry points to resolve; that is not done or
  tested yet, and is listed in `docs/roadmap/CURRENT_STATUS.md` rather than assumed.
- There is no enable/disable switch and no dependency ordering. Both are open work.

## Verification

`tests/test_registry.py` - 12 cases: the seven official names are discovered; a manifest
that is not a `ModuleManifest` becomes broken; an entry point whose module does not exist
becomes broken and the rest survive; alias lookup through `registry.get()`; the ambient
`use()` / `active()` injection.

`tests/test_plugin_example.py` - 7 cases: an example plugin is discovered from a
`.dist-info` built on `sys.path`, and its command actually runs through the router.

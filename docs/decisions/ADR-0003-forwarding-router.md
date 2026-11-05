# ADR-0003 - A module is a forwarding command, not an import

Status: accepted
Date: 2026-11-04

## Context

`levix --help` has to list seven modules and every plugin the user has installed. The
naive way to get that list is to import them. Importing Tube means importing `yt_dlp`,
Music means `sounddevice` and `numpy`, SystemPulse means `psutil` - hundreds of
milliseconds and tens of megabytes for a command that prints text and exits.

| Option | Why it was not chosen |
| --- | --- |
| Import every module CLI at startup | Breaks the lightweight-core promise on the first keystroke; a module with a broken import takes the whole CLI down |
| Re-exec `levix-<module>` as a subprocess | Loses the shared context (paths, config, database, logging), needs one entry point per module, and pays process startup on every call |
| Custom `click.Group.get_command` override | Works, but it is a private-implementation hook in a library LEVIX does not own; Typer does not expose it |
| One forwarding command per manifest | Stdlib-free, keeps the manifest as data, and the module is imported only when it is actually run |

## Decision

`registry.py` reads each manifest's data. `router.py` mounts one Typer command per
manifest whose body is a forward:

```python
app.command(
    command_name,
    help=manifest.summary,
    add_help_option=False,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)(dispatch)
```

and `_forward` hands the untouched argv to the module's own click command, built at that
moment by `registry.build_cli(manifest)` - the single deferred-import site in the project:

```python
result = command.main(
    args=list(ctx.args),
    prog_name=f"levix {manifest.name}",
    standalone_mode=False,
    obj=ctx.obj,
)
```

Three details are load-bearing, and each was learned from a failure:

- **`obj=ctx.obj`.** `command.main()` starts a brand-new click context with no parent, so
  without it the `LevixContext` built by the root callback stops at the forwarding command
  and every module reads its `tube.*` / `music.*` configuration as the built-in fallback.
  A test writes the received object's type to a file to prove it survives
  (`tests/test_router.py::test_a_module_command_receives_the_context_built_by_the_root`).
- **`prog_name=f"levix {name}"`.** click appends the subcommand it is reporting, so a
  prog_name of plain `levix` made `levix monitor cpu --json` blame a command called
  `levix cpu`.
- **exception classification by MRO class name, not `isinstance`.** Typer 0.27 vendors its
  own click fork (`typer._click`), so `isinstance(exc, click.UsageError)` is False for the
  exceptions it actually raises. `main._classify` matches names in `type(exc).__mro__`;
  the installed `click` distribution (8.5) stays a declared dependency for Rich and
  Textual, and is not the click LEVIX runs on.

## Consequences

- `levix --help` and `levix tube -h` import nothing heavy. This is asserted in a child
  interpreter, because the parent test process has already imported psutil and friends:
  `_child_heavy_loads(["--help"])` and `_child_heavy_loads(["tube", "-h"])` must both
  return `[]` for `("psutil", "yt_dlp", "sounddevice", "soundfile", "numpy", "textual")`.
- Exit codes survive the hop: a module's own `typer.Exit(code=7)` and a `LevixError`
  raised inside a module both reach the process exit status unchanged.
- `CommandInfo.aliases` become **top-level shortcuts for the command they name**
  (`levix q hello` is `levix ai ask hello`, and `levix hi alias` is
  `levix hello greet alias` for the example plugin), not shortcuts for the module's group -
  that is what the forwarding loop in `register_modules` does, and the docs say so rather
  than implying `levix hello hi` works.
- A bare module name is a usage error. click 8.5's `no_args_is_help` raises
  `NoArgsIsHelpError` (a `UsageError`), so `levix tube` prints the module's help on
  **stderr** and exits **2**. Tests read stdout and stderr together because of it.
- Because the forwarder sets `ignore_unknown_options`, a typo in a module's flag is
  reported by the module's own parser, not by the core - which is the point, and is why
  `add_help_option=False` (the module owns `-h`).
- The gate is *not* in the router. `levix tube -h` must work with yt-dlp missing, so
  `deps.ensure_dependencies(MANIFEST)` runs inside each module's Typer callback instead.
  That costs one line per module and lets a plugin forget it; `levix.sdk` does not
  re-export the gate today, which is recorded as open work.

## Verification

`tests/test_router.py` - 14 cases, all against a stub module that is not one of the seven,
covering the two heavy-import invariants, context survival, argv survival, module exit
codes, `LevixError` exit codes inside a module, alias mounting, unknown-command reporting
(exit 4 with the registry's own list), the gate's exit 3, help with a missing dependency,
bare-group usage (exit 2), history recording of a forwarded run, and a bad config value
surfacing as exit 5 through the forward.

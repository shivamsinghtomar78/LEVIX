# ADR-0004 - `tomllib` reads, `tomlkit` writes, and comments survive

Status: accepted
Date: 2026-11-04

## Context

LEVIX has one user-editable file, `config.toml`, and a user is expected to edit it by
hand: add a comment explaining why `matrix_fps` is 12, reorder sections, keep a disabled
line as documentation. Then `levix config set general.theme hacker` runs, and whatever
writes that file decides whether the user's work survives.

| Option | Why it was not chosen |
| --- | --- |
| `tomllib` (stdlib) for both directions | It is read-only. There is nothing to write with |
| `tomli-w` over a plain `dict` | Correct TOML, wrong file: every comment, blank line and ordering choice is silently deleted on the first `config set` |
| `pydantic` + a model per section | Validation of ~30 keys buys a compiled `pydantic-core` wheel in the core, slows startup, and complicates a standalone build |
| JSON or YAML | Neither is what a modern Python CLI user expects to hand-edit, and YAML's indentation is a bad fit for a config a program rewrites |
| `tomllib` read + `tomlkit` write | stdlib parse for the read path (no dependency, no version drift), and the one library that models comments as data |

## Decision

Reads go through `tomllib` (`config._read_toml`), writes through `tomlkit`
(`config.write_user_value` / `remove_user_value`), and the two never swap roles. A write
parses the user's existing document, sets one key, and dumps the document back:

```python
doc = read_user_document(paths)
if section not in doc:
    doc.add(section, tomlkit.table())
doc[section][key] = value
paths.config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
```

Validation is a hand-maintained table, `config.SCHEMA: dict[str, dict[str, Spec]]`, where
`Spec` is `kind` plus optional `minimum`, `maximum` and `choices`. It is thirty lines and
it is the only validator in the project.

Resolution order, first writer wins, with the winner recorded per key:

1. packaged `data/defaults.toml` (shipped in the wheel, source `default`)
2. the user's `config.toml` (source `user`)
3. `LEVIX_<SECTION>_<KEY>` environment variables (source `env`)
4. command-line flags, applied by the command that owns them, not by `Config`

`Config.load` refuses to start on a key it does not recognise, in either direction:
a `defaults.toml` that has not kept up with `SCHEMA` raises `"packaged defaults are
missing <section>.<key>"`, and a user file with an unknown section or key raises a
`ConfigError` naming the file. `levix config show` prints the resolved value **and its
source** for every key.

## Consequences

- Comments, blank lines and ordering survive a programmatic write, so `levix config set`
  can be used on a hand-edited file without warning the user first.
- There is no schema drift: adding a key means editing `SCHEMA` **and** `defaults.toml`,
  and forgetting the second one fails loudly at startup rather than producing a `None`
  deep inside a module.
- Unknown keys are an error rather than a warning. A typo in a config file is a real
  mistake, and silently ignoring it means the user believes they changed something.
  The cost is exit 5 (`CONFIG`) for a whole run over one bad line - which is the point of
  reporting the file path in the message.
- Environment overrides are limited to keys whose section already exists in `SCHEMA`, and
  the four variables that are not configuration (`LEVIX_HOME`, `LEVIX_NO_COLOR`,
  `LEVIX_API_KEY`, `LEVIX_AI_API_KEY`) are excluded by name so they cannot masquerade as
  one.
- **A plugin cannot add a configuration section.** `SCHEMA` is owned by the core, so
  `hello.*` in `config.toml` is a `ConfigError`, and the example plugin documents that.
  This is deliberate (a plugin that invents keys invents a second, unvalidated config
  channel) and it is a hole in the plugin promise; the resolution is recorded in
  `docs/roadmap/CURRENT_STATUS.md`, not argued away here.
- Secret-shaped keys are refused by `levix config set` and masked by `config show` /
  `config list` - see `ADR-0005`.
- `levix config reset` writes a `.toml.bak` beside the file before deleting it and asks
  first unless `--yes`, which only skips the prompt for a step the user is doing to their
  own file.

## Verification

`tests/test_config.py` - 17 cases: `LEVIX_HOME` and the per-directory overrides; defaults
load with no user file; `defaults.toml` and `SCHEMA` cover exactly each other in both
directions; layer precedence (`env` over `user` over `default`, reported per key by
`source()`); four parametrised bad files - a string where an int belongs, a value outside
`Spec.maximum`, a value outside `Spec.choices` and a file that is not TOML at all - each
raising `ConfigError` naming the key; an unknown section and an unknown key each rejected;
**a `write_user_value` round-trip over a file the user hand-edited, asserting that both of
its comments and its existing keys are still there afterwards**; `remove_user_value`
falling back to the packaged default and reporting `False` the second time; a coerced
write that is rejected before the file is opened, so nothing is left behind; and
`levix config set ai.api_key …` refusing with exit 5 and naming a command that exists.
`tests/test_router.py::test_a_bad_configuration_value_is_reported_as_a_config_error`
drives the whole path from `LEVIX_GENERAL_HISTORY_LIMIT=not-a-number` to exit 5.

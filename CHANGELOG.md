# Changelog

All notable changes to LEVIX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.4.0 - initial official modules

### Added

- Core engine: lazy `LevixGroup` command routing, `levix.plugins` entry-point
  discovery with origin stamping, layered TOML configuration, shared SQLite storage
  with namespaced migrations, dependency gate, capability probes, redacted rotating
  logs, and a single documented exit-code table.
- Interactive Textual dashboard: manifest-driven module list, keyboard bindings,
  theme selection, recent command history, and module launching through
  `App.suspend()` plus a subprocess so one terminal is never owned by two apps.
- Modules: SystemPulse (`levix monitor`), Hacker (`levix hacker`), Files
  (`levix files`), Tube (`levix tube`), Arcade (`levix game`), Music (`levix music`),
  AI (`levix ai`).
- Platform commands: `dashboard`, `config` (show/list/get/set/unset/reset/path/edit),
  `doctor`, `plugins` (list/info), `update` (check-only), `create-module`.
- Plugin SDK façade (`levix.sdk`) and a generated scaffold that loads through the same
  registry the official modules use.
- Documentation set: requirements, architecture, technology, module specs, plugin
  guide, security model, roadmap and task index.

### Known gaps

- `levix install/uninstall/dev/test/package/publish` are not implemented; installing
  third-party code needs the consent and environment model in
  `docs/plugins/PLUGIN_INSTALLATION.md` settled first.
- No CI matrices, no PyPI upload and no standalone binaries yet.
- Verified on Windows only. Linux and macOS behaviour is designed for, not proven.

## 0.1.0 - 0.3.0

Not released. The project was built from an empty repository through phases 0-3 in a
single pass, and the first published version will be the one that ships the modules.

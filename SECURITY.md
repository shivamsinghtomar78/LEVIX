# Security Policy

## What LEVIX is, in threat terms

LEVIX is a local terminal application that runs with **your** account's privileges. It
has no daemon, no server component, no telemetry, and no accounts of its own. It can
read and write files you can read and write, start subprocesses, and make outbound
HTTPS requests when you ask it to.

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | yes |
| < 0.4 | no - upgrade |

Semantic versioning, with the caveat that anything below 1.0 may change its plugin API
between minor versions.

## In-place mitigations

- **Secrets never reach logs.** A `RedactFilter` on the root logger masks bearer
  headers, `sk-`-shaped tokens, GitHub PATs and `*key=*`/`*token=*`/`*password=*`
  pairs before any handler writes. `levix config list` masks secret-shaped keys.
- **No shell interpolation.** `subprocess` calls pass argument lists with
  `shell=False`. `levix hacker network` and `levix ai command` do not accept a string
  to hand to a shell.
- **AI output is not executed.** `levix ai command` prints the proposed command and
  requires you to type the confirmation word. There is no configuration key that makes
  it run automatically.
- **Destructive file operations require a typed confirmation.** `--yes` is deliberately
  refused for deletes: `require_approval()` prints why and confirms interactively
  anyway. Non-interactive stdin is treated as refusal, not consent.
- **Path validation.** `levix files` resolves and rejects traversal outside the chosen
  root before touching the filesystem.
- **Update never self-installs.** `levix update` performs one HTTPS `GET` to
  `pypi.org/pypi/levix/json` and prints the upgrade command. It does not run pip.
- **TOML and SQLite only.** No external database, no cloud storage, no remote config.

## Network access, disclosed

Only these paths make outbound requests, and only when invoked:

1. `levix update` → PyPI JSON API (check only).
2. `levix ai` → the provider base URL you configured.
3. `levix tube` → whatever URLs you pass to yt-dlp.

Nothing else contacts the network. `levix doctor` and the dashboard are purely local.

## The plugin risk, stated plainly

A LEVIX plugin is ordinary Python installed into the same environment as LEVIX. It
runs with full privileges. Declared `permissions` in a `ModuleManifest` are a
**disclosure to the user, not an enforcement boundary** — there is no Python mechanism
that safely contains arbitrary in-process code, and LEVIX will not pretend otherwise.

Practical guidance: install plugins from sources you would trust with `pip install`.
`levix plugins info` shows the providing distribution and declared permissions so you
can decide before running.

## Reporting a vulnerability

Open a **private** security advisory at
<https://github.com/shivamsinghtomar78/LEVIX/security/advisories/new> rather than a
public issue. Include the version, `levix doctor --json` output (it contains no
secrets), and the smallest reproducing command.

Expect an acknowledgement within 7 days for 0.x releases. Fixes ship in a patch
release with an advisory and a CHANGELOG entry.

## Out of scope

Reports about the security of your own environment, third-party plugins you installed,
vulnerabilities in upstream dependencies (file those upstream, then open an issue if
LEVIX should pin around them), and physical-access attacks on your machine.

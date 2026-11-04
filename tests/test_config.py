"""Paths, config layering and validation - the base every module sits on."""

from __future__ import annotations

import tomllib

import pytest

from levix.config import (
    DEFAULTS_FILE,
    SCHEMA,
    Config,
    ConfigError,
    is_secret_key,
    remove_user_value,
    write_user_value,
)
from levix.errors import EXIT_CANCELLED, EXIT_CONFIG
from levix.paths import resolve_paths


def test_levix_home_redirects_every_directory(levix_home):
    paths = resolve_paths()
    assert paths.config_dir == levix_home / "config"
    assert paths.data_dir == levix_home / "data"
    assert paths.cache_dir == levix_home / "cache"
    assert paths.state_dir == levix_home / "state"
    assert paths.log_dir == levix_home / "log"
    assert paths.config_file.name == "config.toml"
    assert paths.database == levix_home / "data" / "levix.db"


def test_single_directory_override_wins(levix_home, monkeypatch, tmp_path):
    other = tmp_path / "elsewhere"
    monkeypatch.setenv("LEVIX_DATA_DIR", str(other))
    assert resolve_paths().data_dir == other
    assert resolve_paths().config_dir == levix_home / "config"


def test_defaults_load_without_a_user_file(levix_home):
    config = Config.load(resolve_paths().ensure())
    assert config.get("monitor.process_limit") == 15
    assert config.source("monitor.process_limit") == "default"


def test_env_layer_sits_above_the_user_file(levix_home, monkeypatch):
    paths = resolve_paths().ensure()
    paths.config_file.write_text("[monitor]\nprocess_limit = 7\n", encoding="utf-8")
    monkeypatch.setenv("LEVIX_MONITOR_PROCESS_LIMIT", "9")
    config = Config.load(paths)
    assert config.get("monitor.process_limit") == 9
    assert config.source("monitor.process_limit") == "env"


def test_user_value_beats_the_default(levix_home):
    paths = resolve_paths().ensure()
    paths.config_file.write_text("[general]\nhistory_limit = 5\n", encoding="utf-8")
    assert Config.load(paths).get("general.history_limit") == 5


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ('[monitor]\nprocess_limit = "lots"\n', "monitor.process_limit"),
        ("[ai]\nmax_tokens = 0\n", "ai.max_tokens"),
        ('[logging]\nlevel = "shout"\n', "logging.level"),
        ("this is not toml\n", "not valid TOML"),
    ],
)
def test_bad_config_is_a_reported_error_not_a_traceback(levix_home, body, fragment):
    paths = resolve_paths().ensure()
    paths.config_file.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        Config.load(paths)
    assert fragment in str(caught.value)


def test_unknown_section_is_rejected(levix_home):
    paths = resolve_paths().ensure()
    paths.config_file.write_text("[nowhere]\nvalue = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown configuration section"):
        Config.load(paths)


def test_config_error_carries_the_documented_exit_code(levix_home):
    paths = resolve_paths().ensure()
    paths.config_file.write_text("[nowhere]\nvalue = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        Config.load(paths)
    assert caught.value.exit_code == EXIT_CONFIG


def test_packaged_defaults_cover_every_schema_key():
    """`Config.load` raises for a missing default, so this must hold at build time."""
    with DEFAULTS_FILE.open("rb") as handle:
        defaults = tomllib.load(handle)
    for section, keys in SCHEMA.items():
        for key in keys:
            assert key in defaults.get(section, {}), f"defaults.toml is missing {section}.{key}"
    for section, keys in defaults.items():
        for key in keys:
            assert key in SCHEMA.get(section, {}), f"SCHEMA has no {section}.{key}"


def test_unknown_key_in_the_user_file_is_rejected(levix_home):
    paths = resolve_paths().ensure()
    paths.config_file.write_text('[general]\nthem = "hacker"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"unknown configuration key general\.them"):
        Config.load(paths)


def test_a_programmatic_write_keeps_the_users_comments(levix_home):
    """The whole reason writes use tomlkit instead of a dict serialiser."""
    paths = resolve_paths().ensure()
    paths.config_file.write_text(
        "# my LEVIX setup\n"
        "\n"
        "[general]\n"
        "# 3 is plenty\n"
        "history_limit = 3\n"
        "\n"
        "[monitor]\n"
        "interval_seconds = 2.5\n",
        encoding="utf-8",
    )
    assert write_user_value(paths, "general.theme", "hacker") == "hacker"
    kept = paths.config_file.read_text(encoding="utf-8")
    assert "# my LEVIX setup" in kept, "the file's own header comment survived"
    assert "# 3 is plenty" in kept, "a comment on the user's key survived"
    assert "history_limit = 3" in kept
    assert "interval_seconds = 2.5" in kept
    assert 'theme = "hacker"' in kept
    assert Config.load(paths).get("general.theme") == "hacker"
    assert Config.load(paths).source("general.theme") == "user"


def test_unset_returns_the_value_to_the_default(levix_home):
    paths = resolve_paths().ensure()
    write_user_value(paths, "arcade.speed", "2.0")
    assert Config.load(paths).get("arcade.speed") == 2.0
    assert remove_user_value(paths, "arcade.speed") is True
    loaded = Config.load(paths)
    assert loaded.get("arcade.speed") == 1.0
    assert loaded.source("arcade.speed") == "default"
    assert remove_user_value(paths, "arcade.speed") is False, "removing twice says so"


def test_a_coerced_write_rejects_a_value_outside_its_spec(levix_home):
    paths = resolve_paths().ensure()
    with pytest.raises(ConfigError, match="must be <= 4"):
        write_user_value(paths, "arcade.speed", "99")
    # The value is coerced before anything is opened, so a rejected write leaves no file.
    assert not paths.config_file.exists()


def test_config_set_refuses_a_key_that_looks_like_a_credential(run_cli, capsys):
    assert run_cli("config", "set", "ai.base_url", "x") == 0
    assert run_cli("config", "set", "ai.api_key", "sk-whatever") == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "levix ai key set" in err, "the refusal must name a command that exists"
    assert "sk-whatever" not in err + capsys.readouterr().out


def test_the_refusal_names_the_environment_variable_for_that_key(run_cli, capsys):
    run_cli("config", "set", "monitor.client_secret", "abcdef")
    err = capsys.readouterr().err
    assert "LEVIX_MONITOR_CLIENT_SECRET" in err, "the hint must name this key, not the AI one"


def test_a_declared_number_is_not_a_credential():
    # `max_tokens` matched the "token" marker, so `config set ai.max_tokens 512` exited 5
    # while `LEVIX_AI_MAX_TOKENS=512` and a hand-written config.toml were both accepted.
    assert not is_secret_key("ai.max_tokens")
    assert is_secret_key("ai.api_key")
    assert is_secret_key("general.password")
    assert not is_secret_key("general.theme")


def test_max_tokens_is_writable_by_the_command_that_documents_it(run_cli, capsys):
    assert run_cli("config", "set", "ai.max_tokens", "512") == 0
    assert run_cli("config", "get", "ai.max_tokens") == 0
    assert "512" in capsys.readouterr().out
    assert "secret-shaped" not in capsys.readouterr().out


def test_no_declared_key_is_secret_shaped():
    """The mask in `config show`/`config list` is defence in depth, not a live path.

    A secret cannot reach the config layer at all: `config set` refuses marker-shaped
    keys and `Config.load` rejects unknown ones, so nothing in `SCHEMA` is a credential.
    If that stops being true, this test fails and the mask gets exercised for real.
    """
    dotted = [f"{section}.{key}" for section, keys in SCHEMA.items() for key in keys]
    assert not [name for name in dotted if is_secret_key(name)]


def test_reset_yes_cannot_delete_a_configuration_without_a_typed_word(run_cli, levix_home, capsys):
    """`--yes` is accepted and refused, never obeyed, for a destructive action.

    `config reset` was the one command in the tree that honoured `--yes`: it skipped
    `require_approval` entirely, so a piped run with no terminal deleted config.toml after
    printing nothing. The same flag on `files delete`, `game scores --clear` or
    `ai command --run` warns and asks for a typed word.
    """
    assert run_cli("config", "set", "general.theme", "minimal") == 0
    config_file = levix_home / "config" / "config.toml"
    assert config_file.exists()

    # pytest's stdin is not a terminal, which `require_approval` reads as a refusal.
    assert run_cli("config", "reset", "--yes") == EXIT_CANCELLED
    assert config_file.exists(), "--yes deleted a configuration with no confirmation at all"
    assert "--yes cannot authorize a destructive action" in capsys.readouterr().err


def test_reset_without_a_configuration_says_so_and_exits_zero(run_cli, levix_home):
    assert (levix_home / "config" / "config.toml").exists() is False
    assert run_cli("config", "reset", "--yes") == 0

"""Paths, config layering and validation - the base every module sits on."""

from __future__ import annotations

import pytest

from levix.config import Config, ConfigError
from levix.errors import EXIT_CONFIG
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
        ("[monitor]\nprocess_limit = \"lots\"\n", "monitor.process_limit"),
        ("[ai]\nmax_tokens = 0\n", "ai.max_tokens"),
        ("[logging]\nlevel = \"shout\"\n", "logging.level"),
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

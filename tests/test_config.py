"""Tests for Nexa.config module."""

import os
import tempfile
from pathlib import Path

import pytest

from Nexa.config import Config, ConfigValidationError


class TestConfigBasics:
    """Basic Config operations."""

    def test_initial_state_is_empty(self):
        cfg = Config()
        assert not cfg.exists("any.key")

    def test_set_and_get_dotted_key(self):
        cfg = Config()
        cfg.set("server.host", "127.0.0.1")
        assert cfg.get("server.host") == "127.0.0.1"

    def test_get_returns_default_when_missing(self):
        cfg = Config()
        assert cfg.get("missing.key", default=42) == 42

    def test_exists_after_set(self):
        cfg = Config()
        assert not cfg.exists("server.host")
        cfg.set("server.host", "localhost")
        assert cfg.exists("server.host")

    def test_delete_removes_key(self):
        cfg = Config()
        cfg.set("key", "value")
        assert cfg.delete("key") is True
        assert not cfg.exists("key")
        assert cfg.delete("key") is False

    def test_dict_style_access(self):
        cfg = Config()
        cfg["server.port"] = 8080
        assert cfg["server.port"] == 8080
        assert "server.port" in cfg


class TestConfigTomlLoading:
    """TOML file loading."""

    def test_load_from_toml_file(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            """
            [server]
            host = "0.0.0.0"
            port = 8000

            [database]
            url = "sqlite:///db.sqlite3"
            """
        )
        cfg = Config()
        cfg.load(toml_file)
        assert cfg.get("server.host") == "0.0.0.0"
        assert cfg.get("server.port") == 8000
        assert cfg.get("database.url") == "sqlite:///db.sqlite3"

    def test_load_from_toml_bytes(self):
        toml_bytes = b'[app]\nname = "test"\n'
        cfg = Config()
        cfg.load(toml_bytes)
        assert cfg.get("app.name") == "test"

    def test_load_file_not_found_raises(self):
        cfg = Config()
        with pytest.raises(FileNotFoundError):
            cfg.load("/nonexistent/path/config.toml")

    def test_load_override_false_skips_existing(self, tmp_path):
        cfg = Config()
        cfg.set("server.host", "original")
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[server]\nhost = "from_toml"\nport = 9000\n')
        cfg.load(str(toml_file), override=False)
        # Existing key should not be overwritten.
        assert cfg.get("server.host") == "original"
        # New key should be added.
        assert cfg.get("server.port") == 9000


class TestConfigDefaults:
    """Default values."""

    def test_defaults_provided_on_init(self):
        cfg = Config(defaults={"server.host": "127.0.0.1", "server.port": 3000})
        assert cfg.get("server.host") == "127.0.0.1"
        assert cfg.get("server.port") == 3000

    def test_get_with_type_coercion(self):
        cfg = Config()
        cfg.set("port", "8080")
        assert cfg.get("port", type=int) == 8080
        assert isinstance(cfg.get("port", type=int), int)

    def test_get_bool_from_string(self):
        cfg = Config()
        cfg.set("debug", "true")
        assert cfg.get("debug", type=bool) is True

    def test_get_bool_false_from_string(self):
        cfg = Config()
        cfg.set("debug", "false")
        assert cfg.get("debug", type=bool) is False


class TestConfigEnvOverrides:
    """Environment variable overrides."""

    def test_env_override_applied(self, monkeypatch):
        monkeypatch.setenv("NXA_SERVER_HOST", "from_env")
        cfg = Config(env_prefix="NXA")
        cfg.set("server.host", "from_config")
        assert cfg.get("server.host") == "from_env"

    def test_env_override_with_type(self, monkeypatch):
        monkeypatch.setenv("NXA_SERVER_PORT", "9090")
        cfg = Config(env_prefix="NXA")
        cfg.set("server.port", 8080)
        assert cfg.get("server.port", type=int) == 9090

    def test_env_override_custom_prefix(self, monkeypatch):
        monkeypatch.setenv("MYAPP_DATABASE_URL", "postgres://localhost")
        cfg = Config(env_prefix="MYAPP")
        cfg.set("database.url", "sqlite:///db.sqlite3")
        assert cfg.get("database.url") == "postgres://localhost"


class TestConfigValidation:
    """Validation callbacks."""

    def test_validator_passes(self):
        cfg = Config()
        cfg.set("max_connections", 100)
        def validate_positive(value):
            if value <= 0:
                raise ConfigValidationError("must be positive")
        cfg.validate("max_connections", validate_positive)
        # No exception means validation passed.

    def test_validator_raises_on_invalid(self):
        cfg = Config()
        cfg.set("max_connections", -1)
        def validate_positive(value):
            if value <= 0:
                raise ConfigValidationError("must be positive")
        with pytest.raises(ConfigValidationError, match="must be positive"):
            cfg.validate("max_connections", validate_positive)

    def test_validator_registered_for_missing_key_does_not_raise(self):
        cfg = Config()
        def validate_port(value):
            if not (1 <= value <= 65535):
                raise ConfigValidationError(f"Invalid port: {value}")
        cfg.validate("port", validate_port)
        # No value yet, so no validation run.

    def test_validator_raises_for_invalid_value(self):
        cfg = Config()
        cfg.set("port", 99999)
        def validate_port(value):
            if not (1 <= value <= 65535):
                raise ConfigValidationError(f"Invalid port: {value}")
        with pytest.raises(ConfigValidationError, match="Invalid port"):
            cfg.validate("port", validate_port)


class TestConfigIsolation:
    """Per-instance isolation."""

    def test_instances_are_independent(self):
        cfg_a = Config()
        cfg_b = Config()
        cfg_a.set("key", "a_value")
        cfg_b.set("key", "b_value")
        assert cfg_a.get("key") == "a_value"
        assert cfg_b.get("key") == "b_value"

    def test_defaults_not_shared(self):
        cfg_a = Config(defaults={"key": "a_default"})
        cfg_b = Config(defaults={"key": "b_default"})
        assert cfg_a.get("key") == "a_default"
        assert cfg_b.get("key") == "b_default"


class TestConfigAsDict:
    """as_dict round-trip."""

    def test_as_dict_returns_nested_structure(self):
        cfg = Config()
        cfg.set("server.host", "127.0.0.1")
        cfg.set("server.port", 8000)
        cfg.set("database.url", "sqlite:///db.sqlite3")
        d = cfg.as_dict()
        assert d["server"]["host"] == "127.0.0.1"
        assert d["server"]["port"] == 8000
        assert d["database"]["url"] == "sqlite:///db.sqlite3"

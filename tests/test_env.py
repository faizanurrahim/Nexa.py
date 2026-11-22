"""Tests for Nexa.env module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from Nexa.env import Env


class TestEnvBasics:
    """Basic Env operations without persistence."""

    def test_initial_state_is_empty(self):
        env = Env()
        assert not env.exists("ANY_KEY")

    def test_set_and_get(self):
        env = Env()
        env.set("DEBUG", "true")
        assert env.get("DEBUG") == "true"

    def test_get_returns_default_when_missing(self):
        env = Env()
        assert env.get("MISSING", default=42) == 42

    def test_exists_after_set(self):
        env = Env()
        assert not env.exists("FOO")
        env.set("FOO", "bar")
        assert env.exists("FOO")

    def test_delete_removes_value(self):
        env = Env()
        env.set("FOO", "bar")
        assert env.delete("FOO") is True
        assert not env.exists("FOO")
        assert env.delete("FOO") is False

    def test_set_overwrites_existing(self):
        env = Env()
        env.set("FOO", "first")
        env.set("FOO", "second")
        assert env.get("FOO") == "second"


class TestEnvTypeHelpers:
    """Type coercion helpers."""

    def test_bool_true_recognised(self):
        env = Env()
        env.set("FLAG", "true", type=bool)
        assert env.get("FLAG") is True
        assert isinstance(env.get("FLAG"), bool)

    def test_bool_false_recognised(self):
        env = Env()
        env.set("FLAG", "false", type=bool)
        assert env.get("FLAG") is False

    def test_bool_numeric(self):
        env = Env()
        env.set("FLAG", 1, type=bool)
        assert env.get("FLAG") is True

    def test_int_coercion(self):
        env = Env()
        env.set("COUNT", "42", type=int)
        assert env.get("COUNT") == 42
        assert isinstance(env.get("COUNT"), int)

    def test_float_coercion(self):
        env = Env()
        env.set("RATE", "3.14", type=float)
        assert env.get("RATE") == 3.14

    def test_str_coercion(self):
        env = Env()
        env.set("NAME", 123, type=str)
        assert env.get("NAME") == "123"

    def test_bool_invalid_raises(self):
        env = Env()
        with pytest.raises(TypeError):
            env.set("FLAG", "not a bool", type=bool)


class TestEnvPrefix:
    """Key prefixing behaviour."""

    def test_prefix_applied_to_get(self):
        env = Env(prefix="MYAPP")
        env.set("DEBUG", "true")
        # Internal key is prefixed.
        assert env._prefixed("DEBUG") == "MYAPP_DEBUG"

    def test_prefix_auto_added(self):
        env = Env(prefix="APP")
        env.set("DEBUG", "true")
        assert env.exists("DEBUG")
        assert env.get("DEBUG") == "true"

    def test_prefixed_key_accepted_directly(self):
        env = Env(prefix="APP")
        env.set("APP_DEBUG", "true")
        assert env.get("DEBUG") == "true"


class TestEnvOsEnvFallback:
    """Interaction with real OS environment variables."""

    def test_os_env_visible_when_no_in_memory_value(self, monkeypatch):
        monkeypatch.setenv("NXA_FALLBACK", "from_os")
        env = Env(prefix="NXA")
        # No in-memory value set.
        assert env.get("FALLBACK") == "from_os"

    def test_in_memory_overrides_os_env(self, monkeypatch):
        monkeypatch.setenv("NXA_OVERRIDE", "from_os")
        env = Env(prefix="NXA")
        env.set("OVERRIDE", "from_memory")
        assert env.get("OVERRIDE") == "from_memory"

    def test_set_without_override_does_not_touch_os_env(self, monkeypatch):
        monkeypatch.setenv("NXA_PROTECTED", "original")
        env = Env(prefix="NXA")
        env.set("PROTECTED", "new_value")
        # OS env should remain unchanged.
        assert os.environ["NXA_PROTECTED"] == "original"
        # In-memory store has the new value.
        assert env.get("PROTECTED") == "new_value"

    def test_set_with_override_updates_os_env(self, monkeypatch):
        monkeypatch.setenv("NXA_OVERRIDE_ME", "original")
        env = Env(prefix="NXA")
        env.set("OVERRIDE_ME", "new_value", override=True)
        assert os.environ["NXA_OVERRIDE_ME"] == "new_value"
        assert env.get("OVERRIDE_ME") == "new_value"


class TestEnvPersistence:
    """File-based persistence."""

    def test_load_from_json_file(self, tmp_path):
        data_file = tmp_path / "env.json"
        data_file.write_text(json.dumps({"NXA_PERSISTED": "saved_value"}))
        env = Env(prefix="NXA", env_file=data_file)
        assert env.get("PERSISTED") == "saved_value"

    def test_save_persists_values(self, tmp_path):
        data_file = tmp_path / "env.json"
        env = Env(prefix="NXA", env_file=data_file)
        env.set("SAVED", "persisted_value", persist=True)
        assert data_file.is_file()
        loaded = json.loads(data_file.read_text())
        assert loaded["NXA_SAVED"] == "persisted_value"

    def test_load_corrupt_file_starts_fresh(self, tmp_path):
        data_file = tmp_path / "env.json"
        data_file.write_text("not json {{{")
        env = Env(prefix="NXA", env_file=data_file)
        assert not env.exists("ANY_KEY")

    def test_load_missing_file_is_graceful(self, tmp_path):
        missing = tmp_path / "missing.json"
        env = Env(prefix="NXA", env_file=missing)
        assert not env.exists("ANY_KEY")


class TestEnvDump:
    """Dump behaviour including secret redaction."""

    def test_dump_excludes_secrets(self):
        env = Env(prefix="APP")
        env.set("API_KEY", "super-secret-token")
        env.set("DEBUG", "true")
        dumped = env.dump()
        assert dumped["APP_API_KEY"] == "***"
        assert dumped["APP_DEBUG"] == "true"

    def test_dump_with_os_defaults(self, monkeypatch):
        monkeypatch.setenv("APP_OS_DEFAULT", "os_value")
        env = Env(prefix="APP")
        env.set("IN_MEMORY", "mem_value")
        dumped = env.dump(include_defaults=True)
        assert dumped["APP_IN_MEMORY"] == "mem_value"
        # OS-only key is included but redacted only if secret-like.
        assert "APP_OS_DEFAULT" in dumped


class TestEnvLoad:
    """Bulk loading."""

    def test_load_replaces_in_memory_values(self):
        env = Env(prefix="APP")
        env.set("KEY", "old")
        env.load({"KEY": "new", "OTHER": "value"})
        assert env.get("KEY") == "new"
        assert env.get("OTHER") == "value"

    def test_load_does_not_touch_os_env(self, monkeypatch):
        monkeypatch.setenv("APP_OS_KEY", "os_value")
        env = Env(prefix="APP")
        env.load({"OS_KEY": "from_load"})
        # OS env untouched.
        assert os.environ["APP_OS_KEY"] == "os_value"
        # In-memory has the loaded value.
        assert env.get("OS_KEY") == "from_load"


class TestNexaEnvAlias:
    """Legacy NexaEnv alias."""

    def test_nexa_env_delegates_to_env(self):
        from Nexa.env import NexaEnv
        ne = NexaEnv(prefix="TEST")
        ne.set("KEY", "value")
        assert ne.get("KEY") == "value"
        assert ne.exists("KEY")

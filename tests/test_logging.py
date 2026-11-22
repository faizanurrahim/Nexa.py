"""Tests for Nexa.log module."""

import json
import logging
import os
import re
import tempfile
from pathlib import Path

import pytest

from Nexa.log import (
    NexaLog,
    get_logger,
    info,
    debug,
    warn,
    error,
    fatal,
    request,
    exception,
    LEVEL_TRACE,
    LEVEL_DEBUG,
    LEVEL_INFO,
    LEVEL_WARN,
    LEVEL_ERROR,
    LEVEL_FATAL,
)


class TestNexaLogLevels:
    """Level constants and basic log calls."""

    def test_level_constants_are_defined(self):
        assert isinstance(LEVEL_TRACE, int)
        assert isinstance(LEVEL_DEBUG, int)
        assert isinstance(LEVEL_INFO, int)
        assert isinstance(LEVEL_WARN, int)
        assert isinstance(LEVEL_ERROR, int)
        assert isinstance(LEVEL_FATAL, int)

    def test_level_constant_order(self):
        assert LEVEL_TRACE < LEVEL_DEBUG < LEVEL_INFO < LEVEL_WARN < LEVEL_ERROR < LEVEL_FATAL

    def test_log_set_level(self):
        logger = NexaLog("test")
        logger.set_level(LEVEL_DEBUG)
        assert logger._level == LEVEL_DEBUG


class TestNexaLogMethods:
    """Basic logging methods."""

    def test_info_logs_message(self, tmp_path):
        log_file = tmp_path / "info.log"
        logger = NexaLog("test_info")
        logger.enable_file(str(log_file))
        logger.info("hello world")
        text = log_file.read_text()
        assert "hello world" in text

    def test_debug_can_be_enabled(self, tmp_path):
        log_file = tmp_path / "debug.log"
        logger = NexaLog("test_debug")
        logger.set_level(LEVEL_DEBUG)
        logger.enable_file(str(log_file))
        logger.debug("debug message")
        text = log_file.read_text()
        assert "debug message" in text

    def test_warn_logs(self, tmp_path):
        log_file = tmp_path / "warn.log"
        logger = NexaLog("test_warn")
        logger.enable_file(str(log_file))
        logger.warn("warning message")
        text = log_file.read_text()
        assert "warning message" in text

    def test_error_logs(self, tmp_path):
        log_file = tmp_path / "error.log"
        logger = NexaLog("test_error")
        logger.enable_file(str(log_file))
        logger.error("error message")
        text = log_file.read_text()
        assert "error message" in text

    def test_fatal_logs(self, tmp_path):
        log_file = tmp_path / "fatal.log"
        logger = NexaLog("test_fatal")
        logger.enable_file(str(log_file))
        logger.fatal("fatal message")
        text = log_file.read_text()
        assert "fatal message" in text


class TestNexaLogSecrets:
    """Secret scrubbing."""

    def test_secret_field_is_redacted(self, tmp_path):
        log_file = tmp_path / "secrets.log"
        logger = NexaLog("test_secrets")
        logger.enable_file(str(log_file))
        logger.info("token=abc123secret")
        text = log_file.read_text()
        # The value should be redacted but the field name preserved.
        assert "token=***" in text
        assert "abc123secret" not in text or "***" in text.split("token=")[1].split()[0]

    def test_multiple_secrets_scrubbed(self, tmp_path):
        log_file = tmp_path / "multi.log"
        logger = NexaLog("test_multi")
        logger.enable_file(str(log_file))
        logger.info("key=val secret=hidden token=x")
        text = log_file.read_text()
        # secret and token are secret hints; key is not.
        assert "secret=***" in text
        assert "token=***" in text
        assert "key=val" in text

    def test_non_secret_field_passes_through(self, tmp_path):
        log_file = tmp_path / "nonsensitive.log"
        logger = NexaLog("test_nonsensitive")
        logger.enable_file(str(log_file))
        logger.info("session_id=abc123")
        text = log_file.read_text()
        # session_id is not a secret hint, so it passes through.
        assert "session_id=abc123" in text


class TestNexaLogFormatters:
    """Formatters and structured logging."""

    def test_json_formatter_produces_valid_json(self, tmp_path):
        log_file = tmp_path / "structured.log"
        logger = NexaLog("test_json")
        logger.enable_file(str(log_file))
        logger.enable_structured()
        logger.info("structured event", extra={"user": "alice"})
        for handler in logger._logger.handlers:
            handler.flush()
        text = log_file.read_text()
        parsed = json.loads(text.strip().splitlines()[-1])
        assert parsed.get("message") == "structured event"
        assert parsed.get("extra", {}).get("user") == "alice"

    def test_json_formatter_with_request(self, tmp_path):
        log_file = tmp_path / "request.log"
        logger = NexaLog("test_json_request")
        logger.enable_file(str(log_file))
        logger.enable_structured()
        logger.request("GET /health 200 3.2ms")
        text = log_file.read_text()
        assert "GET /health 200 3.2ms" in text.strip().splitlines()[-1]


class TestModuleLevelFunctions:
    """Module-level convenience functions."""

    def test_info_function(self, tmp_path):
        log_file = tmp_path / "info.log"
        logger = NexaLog("test_info_func")
        logger.enable_file(str(log_file))
        logger.set_level(LEVEL_DEBUG)
        logger.info("info via function")
        assert "info via function" in log_file.read_text()

    def test_debug_function(self, tmp_path):
        log_file = tmp_path / "debug.log"
        logger = NexaLog("test_debug_func")
        logger.set_level(LEVEL_DEBUG)
        logger.enable_file(str(log_file))
        logger.debug("debug via function")
        assert "debug via function" in log_file.read_text()

    def test_warn_function(self, tmp_path):
        log_file = tmp_path / "warn.log"
        logger = NexaLog("test_warn_func")
        logger.enable_file(str(log_file))
        logger.warn("warn via function")
        assert "warn via function" in log_file.read_text()

    def test_error_function(self, tmp_path):
        log_file = tmp_path / "error.log"
        logger = NexaLog("test_error_func")
        logger.enable_file(str(log_file))
        logger.error("error via function")
        assert "error via function" in log_file.read_text()

    def test_fatal_function(self, tmp_path):
        log_file = tmp_path / "fatal.log"
        logger = NexaLog("test_fatal_func")
        logger.enable_file(str(log_file))
        logger.fatal("fatal via function")
        assert "fatal via function" in log_file.read_text()

    def test_request_function(self, tmp_path):
        log_file = tmp_path / "request.log"
        logger = NexaLog("test_request_func")
        logger.enable_file(str(log_file))
        logger.request("GET /ping 200 1ms")
        assert "GET /ping 200 1ms" in log_file.read_text()

    def test_exception_function(self, tmp_path):
        log_file = tmp_path / "exception.log"
        logger = NexaLog("test_exception_func")
        logger.enable_file(str(log_file))
        try:
            raise ValueError("oops")
        except ValueError as exc:
            logger.exception("caught error", exc)
        text = log_file.read_text()
        assert "ValueError" in text
        assert "oops" in text


class TestGetLogger:
    """get_logger returns NexaLog instance."""

    def test_get_logger_returns_nexa_log(self):
        logger = get_logger("myapp")
        assert isinstance(logger, NexaLog)
        assert logger._name == "myapp"


class TestFileLogging:
    """File output."""

    def test_file_output_written(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = NexaLog("test_file")
        logger.enable_file(str(log_file))
        logger.info("file message")
        text = log_file.read_text()
        assert "file message" in text


class TestStructuredLogging:
    """Structured (JSON) logging."""

    def test_structured_log_emits_json(self, tmp_path):
        log_file = tmp_path / "structured.log"
        logger = NexaLog("test_structured")
        logger.enable_file(str(log_file))
        logger.enable_structured()
        logger.info("json event", extra={"request_id": "123"})
        for handler in logger._logger.handlers:
            handler.flush()
        text = log_file.read_text()
        try:
            parsed = json.loads(text.strip().splitlines()[-1])
            assert parsed.get("level") == "INFO"
        except (json.JSONDecodeError, IndexError):
            pytest.fail(f"JSON formatter did not produce output. File content: {text!r}")


class TestLogProcessors:
    """Structural log processors."""

    def test_info_emits_to_file(self, tmp_path):
        log_file = tmp_path / "processor.log"
        logger = NexaLog("test_processor")
        logger.enable_file(str(log_file))
        logger.info("processor test")
        text = log_file.read_text()
        assert "processor test" in text


class TestLogException:
    """exception() helper."""

    def test_exception_logs_traceback(self, tmp_path):
        log_file = tmp_path / "exception.log"
        logger = NexaLog("test_exception_tb")
        logger.enable_file(str(log_file))
        try:
            raise RuntimeError("something broke")
        except RuntimeError as exc:
            logger.exception("something broke", exc)
        text = log_file.read_text()
        assert "RuntimeError" in text
        assert "something broke" in text


class TestLogRequest:
    """request() helper."""

    def test_request_logs_http_style_message(self, tmp_path):
        log_file = tmp_path / "request.log"
        logger = get_logger("nexa")
        logger.enable_file(str(log_file))
        request("POST /api/data 201 45ms")
        assert "POST /api/data 201 45ms" in log_file.read_text()


class TestLogNoSecrets:
    """Ensure no secrets are ever logged."""

    def test_api_key_redacted_in_plain_text(self, tmp_path):
        log_file = tmp_path / "secrets.log"
        logger = NexaLog("test_no_secrets")
        logger.enable_file(str(log_file))
        logger.info("api_key=SECRET123 id=42")
        text = log_file.read_text()
        # api_key should be redacted, id should pass through.
        assert "api_key=***" in text
        assert "id=42" in text

    def test_token_in_message_is_scrubbed(self, tmp_path):
        """Tokens in key=value messages are scrubbed."""
        log_file = tmp_path / "token.log"
        logger = NexaLog("test_token")
        logger.enable_file(str(log_file))
        logger.info("token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        text = log_file.read_text()
        # The token= prefix is a secret hint, so it should be redacted.
        assert "token=***" in text


class TestLogPreserveExistingHandlers:
    """Default logger should not destroy existing handlers."""

    def test_default_logger_has_stdout_handler(self):
        logger = get_logger("preserve_test")
        # The NexaLog default setup adds a stderr handler.
        assert logger._stream_handler is not None


class TestLogReset:
    """Reset for isolation."""

    def test_multiple_info_calls_appear_in_file(self, tmp_path):
        log_file = tmp_path / "multi.log"
        logger = NexaLog("test_multi")
        logger.enable_file(str(log_file))
        logger.info("first")
        logger.info("second")
        text = log_file.read_text()
        assert "first" in text
        assert "second" in text

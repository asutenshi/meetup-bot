import json
import logging

from meetup_bot.logging_config import JsonFormatter, configure_logging


def _record(**kwargs: object) -> logging.LogRecord:
    defaults: dict[str, object] = {
        "name": "meetup_bot.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 10,
        "msg": "hello %s",
        "args": ("world",),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(  # type: ignore[arg-type]
        name=defaults["name"],
        level=defaults["level"],
        pathname=defaults["pathname"],
        lineno=defaults["lineno"],
        msg=defaults["msg"],
        args=defaults["args"],
        exc_info=defaults["exc_info"],
    )


def test_json_formatter_emits_required_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "meetup_bot.test"
    assert payload["message"] == "hello world"
    # `ts` — ISO-8601 в UTC.
    assert payload["ts"].endswith("+00:00")


def test_json_formatter_includes_extra_fields() -> None:
    record = _record()
    record.chat_id = 42
    record.reason = "expired"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["chat_id"] == 42
    assert payload["reason"] == "expired"


def test_json_formatter_serialises_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record(exc_info=sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exc"]


def test_json_formatter_output_is_single_line() -> None:
    line = JsonFormatter().format(_record(msg="multi\nline", args=()))

    assert "\n" not in line


def test_configure_logging_replaces_handlers_and_is_idempotent() -> None:
    root = logging.getLogger()
    try:
        configure_logging(level="WARNING")
        configure_logging(level="WARNING")

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.WARNING
    finally:
        # Вернуть логирование в исходное состояние для остальных тестов.
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.WARNING)


def test_configure_logging_quiets_noisy_loggers() -> None:
    root = logging.getLogger()
    try:
        configure_logging(level="DEBUG")

        assert logging.getLogger("aiogram.event").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.WARNING)

"""Structured logging setup — JSON in production, human-readable in dev.
Sensitive values (passwords, tokens, emails) are redacted from log output."""

import os
import re

import structlog


def _redact_sensitive(_logger, _method, event_dict):
    """Strip passwords, tokens, and emails from log events before they hit
    the renderer. Works on both top-level keys and nested dict values."""
    sensitive_keys = {"password", "token", "secret", "api_key", "access_token", "authorization"}
    sensitive_patterns = [
        (r"(?i)bearer\s+[^\s]+", "Bearer [REDACTED]"),
        (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL_REDACTED]"),
    ]

    def _redact_value(v):
        if isinstance(v, str):
            for pattern, replacement in sensitive_patterns:
                v = re.sub(pattern, replacement, v)
        return v

    cleaned = {}
    for key, value in event_dict.items():
        if key.lower() in sensitive_keys:
            cleaned[key] = "[REDACTED]"
        elif isinstance(value, str):
            cleaned[key] = _redact_value(value)
        elif isinstance(value, dict):
            cleaned[key] = {k: _redact_value(v) if isinstance(v, str) else v for k, v in value.items()}
        else:
            cleaned[key] = value
    return cleaned


def configure_logging() -> None:
    """Wire structlog once at app startup.  Production gets JSON; dev gets
    colourised console output."""
    is_production = os.getenv("ENV", "development") == "production"

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_sensitive,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    if is_production:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Also configure the stdlib formatter so uvicorn/gunicorn logs are
    # consistent with our structured output.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_sensitive,
        ],
    )

    import logging
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

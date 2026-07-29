"""Structured logging configuration.

Bridges stdlib ``logging`` into structlog so all ``logging.getLogger``
call sites share one structlog ``ProcessorFormatter`` pipeline. This makes
the spec claim "structlog for structured logging" true for the entire
codebase (DFT-7a3c1e9f), not just native structlog callers.
"""

from __future__ import annotations

import logging
import logging.config

import structlog


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configure structured logging for QuantFlow.

    Stdlib loggers (``logging.getLogger``) and native structlog loggers
    are unified through ``structlog.stdlib.ProcessorFormatter``: stdlib
    records flow in via ``foreign_pre_chain``, native structlog records
    via ``wrap_for_formatter``, both rendered by the same formatter.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        timestamper,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer()
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structlog": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer,
                    ],
                    "foreign_pre_chain": shared_processors,
                },
            },
            "handlers": {
                "default": {
                    "level": level.upper(),
                    "class": "logging.StreamHandler",
                    "formatter": "structlog",
                },
            },
            "loggers": {
                "": {
                    "handlers": ["default"],
                    "level": level.upper(),
                },
            },
        }
    )

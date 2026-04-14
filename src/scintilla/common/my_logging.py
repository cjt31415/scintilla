"""
Reference logging configuration — canonical version.

Claude: When creating a new script from template.py, check that the target
project has src/<project>/common/my_logging.py. If missing, copy this file
there (and create common/__init__.py if needed). If it exists but differs
from this reference, update it to match.

Features:
    - LocalTimeFormatter: GPU servers (coati, spark, orin) run UTC; this
      converts log timestamps to Pacific for easier correlation.
    - Noisy-lib silencing: httpx, sqlalchemy, openai, etc. stay at WARNING.
    - temporary_log_level: context manager for scoped debug logging.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo


class LocalTimeFormatter(logging.Formatter):
    """Convert UTC timestamps to local timezone in log output.

    GPU servers run in UTC, but this shows timestamps in Pacific time
    for easier correlation with local events.
    """

    def __init__(self, fmt=None, datefmt=None,
                 timezone: str = 'America/Los_Angeles'):
        super().__init__(fmt, datefmt)
        self.timezone = ZoneInfo(timezone)

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=ZoneInfo('UTC'))
        dt_local = dt.astimezone(self.timezone)
        if datefmt:
            return dt_local.strftime(datefmt)
        return dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')


def configure_logging(
    log_level: str = 'info',
    use_local_time: bool = True,
    timezone: str = 'America/Los_Angeles',
    include_name: bool = False,
) -> None:
    """Configure root logger with consistent format across all projects.

    Args:
        log_level: One of 'debug', 'info', 'warning', 'error'.
        use_local_time: Convert UTC timestamps to local timezone.
        timezone: Timezone name (default: America/Los_Angeles).
        include_name: Include logger name in output format.
    """
    handler = logging.StreamHandler()

    fmt = ("%(asctime)s - %(name)s - %(levelname)s - %(message)s"
           if include_name
           else "%(asctime)s - %(levelname)s - %(message)s")

    if use_local_time:
        formatter = LocalTimeFormatter(
            fmt=fmt, datefmt='%Y-%m-%d %H:%M:%S', timezone=timezone)
    else:
        formatter = logging.Formatter(fmt=fmt, datefmt='%Y-%m-%d %H:%M:%S')

    handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[handler],
    )

    # Quiet third-party chatter
    for noisy in (
        'openai', 'openai.api_requestor',
        'httpx', 'httpcore', 'anyio',
        'urllib3',
        'sqlalchemy', 'sqlalchemy.engine',
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@contextmanager
def temporary_log_level(logger: logging.Logger, level: int):
    """Context manager to temporarily change a logger's level.

    Usage:
        with temporary_log_level(logger, logging.DEBUG):
            logger.debug("This will be logged")
        # original level restored
    """
    original_level = logger.level
    logger.setLevel(level)
    try:
        yield
    finally:
        logger.setLevel(original_level)

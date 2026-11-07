"""Bounded retry of Telegram rate-limit answers for every Bot API request.

Registered on the bot's HTTP session, so progress edits, command replies and
completion messages all share one policy instead of each call site retrying
on its own (REQ-018).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramRetryAfter

from backend.i18n import t
from backend.log_messages import (
    LOG_TELEGRAM_RATE_LIMIT_WAIT,
    LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES,
)
from backend.tools.logger import logger

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.methods import TelegramMethod

#: Retries after the first attempt before the rate-limit error is raised to the caller.
DEFAULT_MAX_RETRIES = 3
#: Longest ``retry_after`` the bot waits for; a longer flood wait fails at once instead of stalling the update.
DEFAULT_MAX_WAIT_SECONDS = 60.0


class RetryAfterMiddleware(BaseRequestMiddleware):
    """Wait out Telegram ``429 Too Many Requests`` answers within a bounded policy.

    Args:
        max_retries (int): Retries after the first attempt (default: DEFAULT_MAX_RETRIES).
        max_wait_seconds (float): Longest single wait accepted from Telegram (default: DEFAULT_MAX_WAIT_SECONDS).
        sleep: Awaitable sleep function, replaceable in tests (default: asyncio.sleep).
    """

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
        sleep=asyncio.sleep,
    ) -> None:
        self.max_retries = max_retries
        self.max_wait_seconds = max_wait_seconds
        self._sleep = sleep

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[Any],
        bot: "Bot",
        method: "TelegramMethod[Any]",
    ) -> Any:
        attempt = 0
        while True:
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as error:
                attempt += 1
                if attempt > self.max_retries or error.retry_after > self.max_wait_seconds:
                    logger.error(
                        t(LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES).format(attempts=attempt)
                    )
                    raise
                logger.warning(
                    t(LOG_TELEGRAM_RATE_LIMIT_WAIT).format(
                        wait=error.retry_after, preview=type(method).__name__
                    )
                )
                await self._sleep(error.retry_after)

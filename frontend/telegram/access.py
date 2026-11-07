"""Operator access policy for the Telegram bot's operational commands (REQ-015)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.config.settings import settings

if TYPE_CHECKING:
    from aiogram.types import Message


def is_operator(message: "Message") -> bool:
    """Whether the sender is listed in TELEGRAM_ADMIN_IDS.

    The list is empty by default, which closes the operator commands to
    everyone until an operator id is configured.

    Args:
        message (Message): Incoming aiogram message whose sender is checked; no default (required).

    Returns:
        bool: True only for a sender whose Telegram user id is configured as an operator.
    """
    user = message.from_user
    return user is not None and user.id in settings.telegram_admin_ids

import html
import re

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from backend.i18n import t
from backend.log_messages import (
    LOG_STATUS_EDIT_UNEXPECTED,
    LOG_STATUS_MESSAGE_EDIT_FAILED,
    LOG_STATUS_MESSAGE_SEND_FAILED,
)
from backend.tools.logger import logger
from frontend.telegram.messages import (
    MSG_STATUS_CONVERSION_DONE,
    MSG_STATUS_PROCESSING_FAILED,
)


class StatusTracker:
    """Edits a single live progress message in the chat as the job advances.

    Messages are sent with Telegram's HTML parse mode and every dynamic value
    (file name, stage label) is escaped, so a file name such as
    ``my_file*.pdf`` can no longer break the live message the way Markdown did.

    Args:
        bot (Bot): Aiogram Bot instance used for sending and editing messages; no default (required).
        chat_id (int): Numeric chat id the live message lives in; no default (required).
        filename (str): Source filename shown in the message header; no default (required).
        message_thread_id (int | None): Forum-topic thread id to scope the message to, or None for top-level chats (default: None).
    """

    def __init__(self, bot: Bot, chat_id: int, filename: str, message_thread_id: int | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self.filename = filename
        self.message_thread_id = message_thread_id
        self.message_id: int | None = None
        self._last_text: str = ""

    def _header(self) -> str:
        """Return the escaped bold filename line that opens every tracker message."""
        return f"📄 <b>{html.escape(self.filename)}</b>"

    def _build_progress_bar(self, percent: int, width: int = 20) -> str:
        """Assemble a text-based progress bar like ``[████░░░░░░] 40%``.

        Args:
            percent (int): Completion percentage between 0 and 100.
            width (int): Total bar cell count to render (default: 20).

        Returns:
            str: Bracketed bar filled proportionally to ``percent`` followed by the percentage number.
        """
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent}%"

    def _format_message(self, msg: str, percent: int | None = None) -> str:
        """Render one localized stage label into its decorated chat form.

        Appends a progress bar when the stage carries a parseable page count
        (in any active locale form) or an audio-generation percentage, else
        when the API reported an overall percentage; and picks the most fitting
        header emoji from bilingual keyword hints (Portuguese and English) so
        both locales render consistently. The stage text itself always carries
        the meaning: the emoji is decoration only.

        Args:
            msg (str): Localized pipeline stage label received from the job status stream; no default (required).
            percent (int | None): Overall job progress reported by the API, shown as a bar when the stage carries none (default: None).

        Returns:
            str: HTML message with escaped filename header, optional progress bar and escaped stage text.
        """
        text = html.escape(msg)
        match = re.search(r"(?:pagina|página|page)\s*(\d+)\s*(?:de|of)\s*(\d+)", msg, re.IGNORECASE)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            page_percent = int((current / total) * 100) if total else 0
            bar = self._build_progress_bar(page_percent)
            return f"{self._header()}\n\n{text}\n{bar}"

        audio_match = re.search(r"(?:Gerando áudio|spoken audio).*?(\d+)%", msg, re.IGNORECASE)
        if audio_match:
            audio_percent = int(audio_match.group(1))
            bar = self._build_progress_bar(audio_percent)
            return f"{self._header()}\n\n{text}\n{bar}"

        keywords = {
            "baixando": "⬇️",
            "downloading": "⬇️",
            "analisando": "🔍",
            "analyzing": "🔍",
            "separando": "✂️",
            "splitting": "✂️",
            "preparando": "⚙️",
            "preparing": "⚙️",
            "extraido": "✅",
            "exportando": "📝",
            "exporting": "📝",
            "gerando": "📝",
            "generating": "📝",
            "enviando": "📤",
            "sending": "📤",
            "concluida": "✅",
            "concluída": "✅",
            "completed": "✅",
            "finished": "✅",
            "cancelado": "🚫",
            "cancelled": "🚫",
            "erro": "❌",
            "error": "❌",
            "failed": "❌",
            "falha": "❌",
            "failure": "❌",
            "aguardando": "⏳",
            "queued": "⏳",
            "waiting": "⏳",
            "fila": "⏳",
        }

        header = "📄"
        lower = msg.lower()
        for keyword, emoji in keywords.items():
            if keyword in lower:
                header = emoji
                break

        if percent is not None and 0 < percent <= 100:
            return f"{self._header()}\n\n{header} {text}\n{self._build_progress_bar(percent)}"
        return f"{self._header()}\n\n{header} {text}"

    async def __call__(self, msg: str, percent: int | None = None) -> None:
        """Send the progress message once, or edit it in place for later stage updates.

        Args:
            msg (str): Localized stage label to surface in the live message; no default (required).
            percent (int | None): Overall job progress from the API, or None when unknown (default: None).
        """
        text = self._format_message(msg, percent)
        if self.message_id is not None and text == self._last_text:
            # Telegram rejects an edit that changes nothing.
            return
        self._last_text = text

        if self.message_id is None:
            try:
                sent = await self.bot.send_message(
                    self.chat_id, text, parse_mode="HTML",
                    message_thread_id=self.message_thread_id,
                )
                self.message_id = sent.message_id
            except Exception as e:
                logger.warning(
                    t(LOG_STATUS_MESSAGE_SEND_FAILED).format(error=e)
                )
                try:
                    sent = await self.bot.send_message(
                        self.chat_id, html.escape(msg),
                        message_thread_id=self.message_thread_id,
                    )
                    self.message_id = sent.message_id
                except Exception:
                    pass
        else:
            try:
                await self.bot.edit_message_text(
                    text,
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    parse_mode="HTML",
                )
            except TelegramAPIError as e:
                logger.debug(
                    t(LOG_STATUS_MESSAGE_EDIT_FAILED).format(error=e)
                )
            except Exception as e:
                logger.warning(
                    t(LOG_STATUS_EDIT_UNEXPECTED).format(error=e)
                )

    async def finish(self, success: bool = True) -> None:
        """Replace the live message with a localized success or failure final receipt.

        Args:
            success (bool): True edits in a completion receipt, False a processing-failure receipt (default: True).
        """
        if self.message_id is None:
            return
        final = t(MSG_STATUS_CONVERSION_DONE) if success else t(MSG_STATUS_PROCESSING_FAILED)
        try:
            await self.bot.edit_message_text(
                f"{self._header()}\n\n{final}",
                chat_id=self.chat_id,
                message_id=self.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass

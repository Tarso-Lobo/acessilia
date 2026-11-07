import asyncio
import html
import tempfile
import time
import uuid
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, Document, PhotoSize
from aiogram.exceptions import TelegramAPIError

from frontend.telegram.adapters.file_service import download_file
from frontend.clients.api_client import ApiError
from frontend.clients import default_client
from frontend.telegram import user_context

from backend.tools.logger import logger
from backend.i18n import SUPPORTED_LOCALES, get_translations, t
from backend.log_messages import (
    LOG_DOCX_GENERATION_FAILED,
    LOG_MP3_GENERATION_FAILED,
    LOG_TELEGRAM_API_JOB_REJECTED,
    LOG_TELEGRAM_API_CONTACT_FAILED,
    LOG_TELEGRAM_FILE_PROCESSING_ERROR,
    LOG_PDF_UA_GENERATION_FAILED,
    LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED,
    LOG_TELEGRAM_UNHANDLED_ERROR,
)
from backend.services.download_token_service import TOKEN_EXPIRY_DAYS
from backend.tools.validators import MSG_FILE_TOO_LARGE, validate_file
from frontend.telegram.adapters.status_tracker import StatusTracker
from backend.config.settings import settings
from frontend.telegram.messages import (
    MSG_ACCESSIBLE_PACKAGE_READY,
    MSG_CONTACT_SERVER_FAILED,
    MSG_DONE_WITHOUT_LINK,
    MSG_DOWNLOAD_LINK_EMAILED,
    MSG_DOWNLOADING_FILE,
    MSG_EMAIL_DELIVERY_FAILED,
    MSG_EMAIL_DELIVERY_UNCONFIRMED,
    MSG_FILE_DOWNLOAD_FAILED,
    MSG_FILE_RECEIVED,
    MSG_MODE_NAME_DETAILED,
    MSG_MODE_NAME_LOW,
    MSG_MODE_NAME_MEDIUM,
    MSG_MODE_NAME_OCR,
    MSG_PACKAGE_CONTENTS,
    MSG_PACKAGE_OPTIONAL_MISSING,
    MSG_PACKAGE_WARNINGS,
    MSG_PHOTO_RECEIVED,
    MSG_PROCESS_FAILED_BASE,
    MSG_PROCESSING_ERROR_GENERIC,
    MSG_PROCESSING_TIMEOUT,
    MSG_QUEUE_POSITION,
    MSG_SUBMIT_FAILED,
    MSG_SUBMITTED_WITH_MODE,
    MSG_TASK_CANCELLED,
    MSG_TASK_ENQUEUED,
    MSG_WAITING_IN_QUEUE,
)

router = Router()

client = default_client

#: Seconds between two job-status polls while a conversion runs.
POLL_INTERVAL_SECONDS = 3.0
#: Longest the bot keeps polling, after a job is done, for the service to report the e-mail delivery outcome.
EMAIL_DELIVERY_WAIT_SECONDS = 60.0
#: Largest file the Telegram Bot API lets a bot download (getFile); bigger uploads can never reach the service.
TELEGRAM_BOT_DOWNLOAD_LIMIT_MB = 20
#: Validity of the download link: the service's token lifetime (backend/services/download_token_service.py).
DOWNLOAD_LINK_VALIDITY_DAYS = TOKEN_EXPIRY_DAYS

#: Description-mode names shown in the receipt; "normal" is the API's alias of the medium (default) mode.
_MODE_NAMES: dict[str, str] = {
    "detalhado": MSG_MODE_NAME_DETAILED,
    "medio": MSG_MODE_NAME_MEDIUM,
    "normal": MSG_MODE_NAME_MEDIUM,
    "baixo": MSG_MODE_NAME_LOW,
    "ocr": MSG_MODE_NAME_OCR,
}

#: Display names of the formats the download endpoint can list for a package.
_FORMAT_LABELS: dict[str, str] = {
    "txt": "TXT",
    "html": "HTML",
    "docx": "DOCX",
    "pdf_ua": "PDF/UA",
    "pdf": "PDF",
    "mp3": "MP3",
    "zip": "ZIP",
}

#: Optional exports whose failure the worker records in the job's ``erros``, keyed by the failure log template.
_OPTIONAL_EXPORT_FAILURES: tuple[tuple[str, str], ...] = (
    (LOG_DOCX_GENERATION_FAILED, "DOCX"),
    (LOG_PDF_UA_GENERATION_FAILED, "PDF/UA"),
    (LOG_MP3_GENERATION_FAILED, "MP3"),
)

#: File suffixes inferred from the MIME type when Telegram sends a document without a usable file name.
_MIME_SUFFIXES: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}


def _document_filename(document: Document) -> str:
    """Return the base file name of an upload, inferring the suffix from its MIME type when missing.

    Args:
        document (Document): Telegram document whose ``file_name`` may be absent or carry no suffix; no default (required).

    Returns:
        str: A bare file name (no directory part) suitable for validation and display.
    """
    filename = Path((document.file_name or "document").replace("\\", "/")).name or "document"
    if not Path(filename).suffix:
        suffix = _MIME_SUFFIXES.get((getattr(document, "mime_type", None) or "").lower())
        if suffix:
            filename += suffix
    return filename


def _telegram_size_error(file_size: int) -> str | None:
    """Reject a file bigger than the bot can download or the service accepts.

    Args:
        file_size (int): Size in bytes reported by Telegram; 0 when unknown.

    Returns:
        str | None: Localized error for an oversized file, or None when the size is acceptable.
    """
    limit_mb = min(settings.max_file_size_mb, TELEGRAM_BOT_DOWNLOAD_LIMIT_MB)
    if file_size > limit_mb * 1024 * 1024:
        return t(MSG_FILE_TOO_LARGE).format(limit=limit_mb)
    return None


def _receipt(base_message_id: str, mode: str) -> str:
    """Build the acknowledgement naming the description mode the file is submitted with.

    Args:
        base_message_id (str): MSG_FILE_RECEIVED or MSG_PHOTO_RECEIVED.
        mode (str): Description mode taken from the sender's context (e.g. "detalhado", "normal").

    Returns:
        str: Localized receipt text.
    """
    mode_name = t(_MODE_NAMES.get(mode, MSG_MODE_NAME_MEDIUM))
    return f"{t(base_message_id)}\n{t(MSG_SUBMITTED_WITH_MODE).format(mode=mode_name)}"


async def _send_update(message: Message, text: str) -> bool:
    """Send a job update as a reply in the sender's chat and topic.

    Rate-limit answers are retried by the session's RetryAfterMiddleware; an
    update still undeliverable after that policy is logged for the operator.

    Args:
        message (Message): The user's original upload, replied to and scoped by chat and topic; no default (required).
        text (str): Localized HTML text whose dynamic values the caller already escaped; no default (required).

    Returns:
        bool: True when Telegram accepted the message.
    """
    kwargs = {}
    if message.message_thread_id is not None:
        kwargs["message_thread_id"] = message.message_thread_id
    try:
        await message.bot.send_message(
            message.chat.id,
            text,
            reply_to_message_id=message.message_id,
            **kwargs,
        )
        return True
    except TelegramAPIError as error:
        logger.error(t(LOG_TELEGRAM_UNHANDLED_ERROR).format(error=error))
        return False


@router.message(F.document)
async def handle_document(message: Message) -> None:
    """Incoming document file handler; validates, acknowledges receipt in the active locale then starts processing.

    Args:
        message (Message): Aiogram Message containing the user-sent Document attachment; no default (required).
    """
    document: Document | None = message.document
    if document is None:
        return

    filename = _document_filename(document)
    file_size = document.file_size or 0

    valid, error_msg = validate_file(filename, file_size)
    if not valid:
        await message.answer(error_msg)
        return
    size_error = _telegram_size_error(file_size)
    if size_error:
        await message.answer(size_error)
        return

    state_key = user_context.get_user_state_key(message)
    mode = user_context.user_modes.pop(state_key, "normal")
    await message.answer(_receipt(MSG_FILE_RECEIVED, mode))
    await process_file(message, document.file_id, filename, mode=mode)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Incoming photo handler; acknowledges receipt in the active locale then starts processing as image.png.

    Args:
        message (Message): Aiogram Message containing one or more PhotoSize entries; no default (required).
    """
    photo: PhotoSize | None = message.photo[-1] if message.photo else None
    if photo is None:
        return

    size_error = _telegram_size_error(getattr(photo, "file_size", None) or 0)
    if size_error:
        await message.answer(size_error)
        return

    state_key = user_context.get_user_state_key(message)
    mode = user_context.user_modes.pop(state_key, "normal")
    await message.answer(_receipt(MSG_PHOTO_RECEIVED, mode))
    await process_file(message, photo.file_id, "image.png", mode=mode)


async def process_file(
    message: Message,
    file_id: str,
    filename: str,
    mode: str = "normal",
) -> None:
    """Download a remote file locally, submit it to the processing API and wait for completion.

    Args:
        message (Message): Aiogram Message triggering the job; provides the sender-scoped state and chat context; no default (required).
        file_id (str): Telegram unique file identifier of the received attachment; no default (required).
        filename (str): Original filename to store and report inside the job; no default (required).
        mode (str): Description-detail preset requested by the user's last /detalhado|/medio|/baixo command (default: "normal").
    """
    filename = Path(filename.replace("\\", "/")).name or "document"
    message_thread_id = message.message_thread_id
    tracker = StatusTracker(
        message.bot, message.chat.id, filename, message_thread_id=message_thread_id
    )
    state_key = user_context.get_user_state_key(message)
    email = user_context.user_emails.get(state_key)

    try:
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
            input_path = Path(tmpdir) / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
            await tracker(t(MSG_DOWNLOADING_FILE))
            try:
                await download_file(message.bot, file_id, input_path)
            except Exception:
                logger.exception(t(LOG_TELEGRAM_FILE_PROCESSING_ERROR))
                await tracker.finish(success=False)
                await message.answer(t(MSG_FILE_DOWNLOAD_FAILED))
                return

            try:
                result = await client.submit_job(
                    input_path,
                    filename,
                    mode=mode,
                    email=email,
                    source="telegram",
                )
            except ApiError as e:
                logger.warning(
                    t(LOG_TELEGRAM_API_JOB_REJECTED).format(
                        status_code=e.status_code, detail=e.detail
                    )
                )
                await tracker.finish(success=False)
                await message.answer(
                    t(MSG_SUBMIT_FAILED).format(
                        status_code=e.status_code, detail=html.escape(str(e.detail))
                    )
                )
                return
            except Exception:
                logger.exception(t(LOG_TELEGRAM_API_CONTACT_FAILED))
                await tracker.finish(success=False)
                await message.answer(t(MSG_CONTACT_SERVER_FAILED))
                return

        user_context.user_emails.pop(state_key, None)
        task_id = result["task_id"]
        position = result.get("position", 1)
        user_context.user_task_ids[state_key] = task_id

        await tracker(t(MSG_TASK_ENQUEUED).format(task_id=task_id))
        if position > 1:
            await message.answer(
                t(MSG_QUEUE_POSITION).format(position=position)
            )

        await _poll_job(message, tracker, task_id, email)
    except Exception:
        logger.exception(t(LOG_TELEGRAM_FILE_PROCESSING_ERROR))
        await tracker.finish(success=False)
        await message.answer(t(MSG_PROCESSING_ERROR_GENERIC))


async def _poll_job(
    message: Message,
    tracker: StatusTracker,
    task_id: str,
    email: str | None,
) -> None:
    """Poll the API for a task's status until it completes, fails or the request timeout elapses.

    Args:
        message (Message): Aiogram Message used to deliver thread-scoped replies; no default (required).
        tracker (StatusTracker): Status message updater bound to the chat and file already initialized by the caller; no default (required).
        task_id (str): Task identifier returned by the API at submit time; no default (required).
        email (str|None): Deliver-to e-mail stored via /email or None when the user has not configured one yet; no default (required at callers).
    """
    deadline = time.monotonic() + max(settings.request_timeout, 60)
    last_update: tuple[str, int] | None = None

    while time.monotonic() < deadline:
        try:
            status = await client.get_job_status(task_id)
        except Exception as e:
            logger.warning(
                t(LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED).format(task_id=task_id, error=e)
            )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        st = status.get("status", "queued")
        etapa = status.get("etapa_atual") or ""
        pct = int((status.get("progresso") or 0.0) * 100)

        if (etapa, pct) != last_update:
            if st == "queued":
                await tracker(t(MSG_WAITING_IN_QUEUE).format(step=etapa))
            elif etapa:
                await tracker(etapa, percent=pct)
            last_update = (etapa, pct)

        if st == "done":
            await _deliver_result(message, tracker, task_id, status, email)
            return

        if st == "error":
            await tracker.finish(success=False)
            erros = status.get("erros") or []
            msg = t(MSG_PROCESS_FAILED_BASE)
            if erros:
                # The fatal error is the last one; earlier entries are optional
                # export warnings recorded before it.
                msg += f"\n{html.escape(str(erros[-1]))}"
            await _send_update(message, msg)
            return

        if st == "cancelled":
            await tracker.finish(success=False)
            await _send_update(message, t(MSG_TASK_CANCELLED))
            return

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    await tracker.finish(success=False)
    await _send_update(message, t(MSG_PROCESSING_TIMEOUT))


async def _deliver_result(
    message: Message,
    tracker: StatusTracker,
    task_id: str,
    status: dict,
    email: str | None,
) -> None:
    """Report a finished job: the link, what the package really holds, and the e-mail outcome.

    A job the service marks as done without a download link is reported as a
    failure, so the user never gets a success-shaped reply without a result.

    Args:
        message (Message): The user's original upload, replied to; no default (required).
        tracker (StatusTracker): Live progress message to close; no default (required).
        task_id (str): Job identifier, polled again for the e-mail delivery outcome; no default (required).
        status (dict): The ``done`` job status returned by the API; no default (required).
        email (str | None): Address configured via /email for this job, or None; no default (required).
    """
    url = status.get("download_url")
    if not url:
        await tracker.finish(success=False)
        await _send_update(message, t(MSG_DONE_WITHOUT_LINK))
        return

    await tracker.finish(success=True)
    parts = [
        t(MSG_ACCESSIBLE_PACKAGE_READY).format(
            days=DOWNLOAD_LINK_VALIDITY_DAYS, url=html.escape(url)
        )
    ]
    delivered = await _package_formats(task_id, url)
    if delivered:
        labels = ", ".join(_FORMAT_LABELS.get(ext, ext.upper()) for ext in delivered)
        parts.append(t(MSG_PACKAGE_CONTENTS).format(formats=html.escape(labels)))

    warnings = [str(error) for error in status.get("erros") or []]
    missing = _missing_optional_formats(warnings)
    if missing:
        parts.append(t(MSG_PACKAGE_OPTIONAL_MISSING).format(formats=", ".join(missing)))
    elif warnings:
        parts.append(t(MSG_PACKAGE_WARNINGS))
    await _send_update(message, "\n\n".join(parts))

    if email:
        delivery = await _wait_email_delivery(task_id, status.get("email_delivery"))
        if delivery == "sent":
            notice = MSG_DOWNLOAD_LINK_EMAILED
        elif delivery == "failed":
            notice = MSG_EMAIL_DELIVERY_FAILED
        else:
            notice = MSG_EMAIL_DELIVERY_UNCONFIRMED
        await _send_update(message, t(notice).format(email=html.escape(email)))


async def _package_formats(task_id: str, download_url: str) -> list[str]:
    """List the formats the service actually stored for a download link.

    Args:
        task_id (str): Job identifier, used in the log line instead of the secret download token; no default (required).
        download_url (str): The job's download URL, ending in its download token; no default (required).

    Returns:
        list[str]: Format extensions (e.g. ``["txt", "html", "zip"]``); empty when the listing is unavailable.
    """
    token = download_url.rstrip("/").rsplit("/", 1)[-1]
    try:
        info = await client.get_download_info(token)
    except Exception as error:
        logger.warning(
            t(LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED).format(task_id=task_id, error=error)
        )
        return []
    formats = info.get("formats") if isinstance(info, dict) else None
    if not isinstance(formats, list):
        return []
    return [
        str(entry["ext"])
        for entry in formats
        if isinstance(entry, dict) and entry.get("ext")
    ]


def _localized_prefixes(message_id: str) -> set[str]:
    """Return the text before ``{error}`` of a failure template in every supported locale.

    The worker records failures in the server's locale, which can differ from
    the locale the bot answers this user in.
    """
    variants = {message_id}
    for locale in SUPPORTED_LOCALES:
        catalog = get_translations(locale)
        if catalog is not None:
            variants.add(str(catalog.gettext(message_id)))
    return {variant.split("{error}")[0] for variant in variants if variant.split("{error}")[0]}


def _missing_optional_formats(errors: list[str]) -> list[str]:
    """Name the optional formats whose export failure the job recorded.

    Args:
        errors (list[str]): The job's ``erros`` entries; no default (required).

    Returns:
        list[str]: Display names of the missing optional formats, in a stable order.
    """
    missing = []
    for template, label in _OPTIONAL_EXPORT_FAILURES:
        prefixes = _localized_prefixes(template)
        if any(error.startswith(prefix) for error in errors for prefix in prefixes):
            missing.append(label)
    return missing


async def _wait_email_delivery(task_id: str, delivery: str | None) -> str | None:
    """Poll briefly for the e-mail delivery outcome the worker records after marking the job done.

    Args:
        task_id (str): Job identifier to poll; no default (required).
        delivery (str | None): ``email_delivery`` from the done status ("pending", "sent", "failed", "unknown" or None).

    Returns:
        str | None: The last outcome seen; still "pending" when the wait ran out.
    """
    deadline = time.monotonic() + EMAIL_DELIVERY_WAIT_SECONDS
    while delivery == "pending" and time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            delivery = (await client.get_job_status(task_id)).get("email_delivery")
        except Exception as error:
            logger.warning(
                t(LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED).format(task_id=task_id, error=error)
            )
    return delivery

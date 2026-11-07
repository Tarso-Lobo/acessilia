"""Telegram bot behaviour required by specs/telegram-bot (REQ-001 ... REQ-020)."""

import asyncio
from types import SimpleNamespace

import pytest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from backend.api.routes.download import MEDIA_TYPES
from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import LOG_DOCX_GENERATION_FAILED, LOG_MP3_GENERATION_FAILED
from backend.tools.validators import MSG_FILE_TOO_LARGE, MSG_INVALID_EMAIL_ADDRESS
from frontend.telegram import user_context
from frontend.telegram.adapters.status_tracker import StatusTracker
from frontend.telegram.handlers import document as doc_module
from frontend.telegram.handlers import start as start_module
from frontend.telegram.messages import (
    MSG_ACCESSIBLE_PACKAGE_READY,
    MSG_CACHE_CLEARED,
    MSG_DONE_WITHOUT_LINK,
    MSG_DOWNLOAD_LINK_EMAILED,
    MSG_EMAIL_DELIVERY_FAILED,
    MSG_FEEDBACK_TEXT_REQUIRED,
    MSG_FEEDBACK_THANKS,
    MSG_FILE_DOWNLOAD_FAILED,
    MSG_FORMATS_TEXT,
    MSG_HELP_TEXT,
    MSG_MODE_NAME_DETAILED,
    MSG_MODE_NAME_MEDIUM,
    MSG_OPERATOR_ONLY,
    MSG_PACKAGE_CONTENTS,
    MSG_PACKAGE_OPTIONAL_MISSING,
    MSG_PACKAGE_WARNINGS,
    MSG_STATE_PROCESSING,
    MSG_STATUS_CONVERSION_DONE,
    MSG_SUBMIT_FAILED,
    MSG_SUBMITTED_WITH_MODE,
    MSG_TASK_CANCEL_REQUESTED,
)
from frontend.telegram.middlewares.retry_middleware import RetryAfterMiddleware
from frontend.clients.api_client import ApiError
from tests.test_telegram_client import (
    _FakeBot,
    _FakeDocument,
    _FakeMessage,
    _fake_pdf_bytes,
)

URL = "http://localhost:8001/download/tok123"
KEY = (123, None, 456)


class _ScriptedClient:
    """Fake API client returning scripted job statuses and a download listing."""

    def __init__(self, statuses, formats=("txt", "html", "zip"), download_error=None):
        self._statuses = list(statuses)
        self.formats = formats
        self.download_error = download_error
        self.submissions = []
        self.download_tokens = []

    async def submit_job(self, file_path, filename, **kwargs):
        self.submissions.append((filename, kwargs))
        return {"task_id": "task1", "position": 1, "message": "ok"}

    async def get_job_status(self, task_id):
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]

    async def get_download_info(self, token):
        self.download_tokens.append(token)
        if self.download_error:
            raise self.download_error
        return {
            "filename": "doc.pdf",
            "stem": "doc",
            "formats": [{"ext": ext, "label": ext, "size": "1 KB", "url": ""} for ext in self.formats],
        }


def _status(state="done", **extra):
    status = {
        "task_id": "task1",
        "arquivo": "doc.pdf",
        "status": state,
        "progresso": 1.0 if state == "done" else 0.5,
        "etapa_atual": "stage",
        "erros": [],
        "download_url": URL if state == "done" else None,
    }
    status.update(extra)
    return status


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "temp_dir", tmp_path)
    monkeypatch.setattr(settings, "max_file_size_mb", 50)
    monkeypatch.setattr(settings, "telegram_admin_ids", frozenset())
    monkeypatch.setattr(doc_module, "POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(doc_module, "EMAIL_DELIVERY_WAIT_SECONDS", 1.0)
    for store in (user_context.user_modes, user_context.user_emails, user_context.user_task_ids):
        store.clear()
    yield monkeypatch
    for store in (user_context.user_modes, user_context.user_emails, user_context.user_task_ids):
        store.clear()


def _run_document(monkeypatch, client, *, filename="doc.pdf", size=None, mime_type=None, bot=None):
    monkeypatch.setattr(doc_module, "client", client)
    content = _fake_pdf_bytes()
    bot = bot or _FakeBot(content)
    document = SimpleNamespace(
        file_name=filename,
        file_size=len(content) if size is None else size,
        file_id="file1",
        mime_type=mime_type,
    )
    message = _FakeMessage(bot, document=document)
    asyncio.run(doc_module.handle_document(message))
    return message, bot


# --- REQ-011 / REQ-020: help and format catalog -------------------------------


def test_formats_list_every_deliverable_and_nothing_else():
    text = t(MSG_FORMATS_TEXT)
    labels = {"txt": "TXT", "html": "HTML", "docx": "DOCX", "pdf_ua": "PDF/UA", "mp3": "MP3", "zip": "ZIP"}
    # "pdf" only serves links issued before PDF/UA replaced it.
    assert set(MEDIA_TYPES) - {"pdf"} == set(labels)
    for label in labels.values():
        assert label in text
    assert "Markdown" not in text
    assert "Searchable PDF" not in text


@pytest.mark.parametrize("command", ["cmd_start", "cmd_formats"])
def test_accepted_inputs_follow_the_validated_extensions(isolated, command):
    isolated.setattr(settings, "allowed_extensions", {".pdf", ".docx", ".png", ".xyz"})
    message = _FakeMessage(_FakeBot(b""))

    asyncio.run(getattr(start_module, command)(message))

    assert "PDF, DOCX, PNG, XYZ" in message.answers[0]
    assert "BMP" not in message.answers[0]


def test_help_lists_delivery_and_operator_commands():
    text = t(MSG_HELP_TEXT)
    for command in ("/email", "/status", "/cancel", "/feedback", "/health", "/clear", "/formats"):
        assert command in text


# --- REQ-001: validation before conversion -----------------------------------


def test_document_over_telegram_download_limit_is_rejected_before_download(isolated):
    client = _ScriptedClient([_status()])
    message, bot = _run_document(isolated, client, size=21 * 1024 * 1024)

    limit = doc_module.TELEGRAM_BOT_DOWNLOAD_LIMIT_MB
    assert message.answers == [t(MSG_FILE_TOO_LARGE).format(limit=limit)]
    assert client.submissions == []
    assert bot.sent == []


def test_photo_over_limit_is_rejected(isolated):
    isolated.setattr(doc_module, "client", _ScriptedClient([_status()]))
    photo = SimpleNamespace(file_id="p1", file_size=30 * 1024 * 1024)
    message = _FakeMessage(_FakeBot(b""), photo=[photo])

    asyncio.run(doc_module.handle_photo(message))

    assert message.answers == [t(MSG_FILE_TOO_LARGE).format(limit=20)]


def test_document_without_name_takes_its_suffix_from_the_mime_type(isolated):
    client = _ScriptedClient([_status()])
    _run_document(isolated, client, filename=None, mime_type="application/pdf")

    assert client.submissions[0][0] == "document.pdf"


def test_telegram_download_failure_is_reported_without_submitting(isolated):
    class _BrokenBot(_FakeBot):
        async def get_file(self, file_id):
            raise RuntimeError("file is too big")

    client = _ScriptedClient([_status()])
    message, _ = _run_document(isolated, client, bot=_BrokenBot(b""))

    assert t(MSG_FILE_DOWNLOAD_FAILED) in message.answers
    assert client.submissions == []


# --- REQ-005 / REQ-006: description mode -------------------------------------


def test_receipt_names_the_mode_and_defaults_to_medium(isolated):
    message, _ = _run_document(isolated, _ScriptedClient([_status()]))
    medium = t(MSG_SUBMITTED_WITH_MODE).format(mode=t(MSG_MODE_NAME_MEDIUM))
    assert medium in message.answers[0]

    user_context.user_modes[KEY] = "detalhado"
    client = _ScriptedClient([_status()])
    message, _ = _run_document(isolated, client)
    detailed = t(MSG_SUBMITTED_WITH_MODE).format(mode=t(MSG_MODE_NAME_DETAILED))
    assert detailed in message.answers[0]
    assert client.submissions[0][1]["mode"] == "detalhado"
    assert KEY not in user_context.user_modes


# --- REQ-003 / REQ-004 / REQ-020: completion ---------------------------------


def test_completion_reports_link_expiry_and_real_package_contents(isolated):
    client = _ScriptedClient([_status()], formats=("txt", "html", "docx", "zip"))
    _, bot = _run_document(isolated, client)

    done = t(MSG_ACCESSIBLE_PACKAGE_READY).format(
        days=doc_module.DOWNLOAD_LINK_VALIDITY_DAYS, url=URL
    )
    assert any(done in text for text in bot.sent)
    assert any(t(MSG_PACKAGE_CONTENTS).format(formats="TXT, HTML, DOCX, ZIP") in text for text in bot.sent)
    assert client.download_tokens == ["tok123"]
    assert any(t(MSG_STATUS_CONVERSION_DONE) in text for text in bot.edited)


def test_completion_names_failed_optional_exports(isolated):
    errors = [
        t(LOG_DOCX_GENERATION_FAILED).format(error="toolbox down"),
        t(LOG_MP3_GENERATION_FAILED).format(error="tts down"),
    ]
    client = _ScriptedClient([_status(erros=errors)])
    _, bot = _run_document(isolated, client)

    missing = t(MSG_PACKAGE_OPTIONAL_MISSING).format(formats="DOCX, MP3")
    assert any(missing in text for text in bot.sent)


def test_completion_with_unrecognized_warning_says_formats_may_be_missing(isolated):
    client = _ScriptedClient([_status(erros=["something odd"])], download_error=RuntimeError("down"))
    _, bot = _run_document(isolated, client)

    assert any(t(MSG_PACKAGE_WARNINGS) in text for text in bot.sent)
    # The link is still delivered when the listing is unavailable.
    assert any(URL in text for text in bot.sent)


def test_done_without_link_is_reported_as_failure(isolated):
    client = _ScriptedClient([_status(download_url=None)])
    _, bot = _run_document(isolated, client)

    assert any(t(MSG_DONE_WITHOUT_LINK) in text for text in bot.sent)
    assert not any(t(MSG_STATUS_CONVERSION_DONE) in text for text in bot.edited)


def test_api_rejection_detail_is_escaped(isolated):
    class _Rejecting(_ScriptedClient):
        async def submit_job(self, file_path, filename, **kwargs):
            raise ApiError(400, "<bad> & worse")

    message, _ = _run_document(isolated, _Rejecting([_status()]))

    expected = t(MSG_SUBMIT_FAILED).format(status_code=400, detail="&lt;bad&gt; &amp; worse")
    assert expected in message.answers


# --- REQ-012: e-mail delivery -------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "notice"),
    [("sent", MSG_DOWNLOAD_LINK_EMAILED), ("failed", MSG_EMAIL_DELIVERY_FAILED)],
)
def test_email_delivery_outcome_is_reported(isolated, outcome, notice):
    user_context.user_emails[KEY] = "me@example.com"
    client = _ScriptedClient(
        [
            _status(email_delivery="pending"),
            _status(email_delivery="pending"),
            _status(email_delivery=outcome),
        ]
    )
    _, bot = _run_document(isolated, client)

    assert client.submissions[0][1]["email"] == "me@example.com"
    assert bot.sent[-1] == t(notice).format(email="me@example.com")


def test_invalid_email_is_refused(isolated):
    message = _FakeMessage(_FakeBot(b""), text="/email not-an-address")

    asyncio.run(start_module.cmd_email(message))

    assert t(MSG_INVALID_EMAIL_ADDRESS) in message.answers[0]
    assert KEY not in user_context.user_emails


# --- REQ-007 / REQ-008 / REQ-019: status and cancellation --------------------


def test_status_states_the_job_in_words(isolated):
    user_context.user_task_ids[KEY] = "task1"
    isolated.setattr(start_module, "client", _ScriptedClient([_status("processing")]))
    message = _FakeMessage(_FakeBot(b""))

    asyncio.run(start_module.cmd_status(message))

    assert t(MSG_STATE_PROCESSING) in message.answers[0]
    assert "50%" in message.answers[0]


def test_cancel_of_a_running_job_reports_a_request_and_keeps_tracking(isolated):
    class _Client:
        async def cancel_job(self, task_id):
            return {"task_id": task_id, "status": "cancelling"}

    user_context.user_task_ids[KEY] = "task1"
    isolated.setattr(start_module, "client", _Client())
    message = _FakeMessage(_FakeBot(b""))

    asyncio.run(start_module.cmd_cancel(message))

    assert message.answers == [t(MSG_TASK_CANCEL_REQUESTED).format(task_id="task1")]
    assert user_context.user_task_ids[KEY] == "task1"


# --- REQ-014 / REQ-015: operator commands ------------------------------------


@pytest.mark.parametrize("command", ["cmd_health", "cmd_limpar"])
def test_operator_commands_are_closed_to_other_users(isolated, command):
    async def must_not_run():
        raise AssertionError("cache cleared by a non-operator")

    isolated.setattr(start_module, "clear_cache", must_not_run)
    message = _FakeMessage(_FakeBot(b""))

    asyncio.run(getattr(start_module, command)(message))

    assert message.answers == [t(MSG_OPERATOR_ONLY)]


def test_operator_can_clear_the_cache(isolated):
    async def cleared():
        return 3

    isolated.setattr(settings, "telegram_admin_ids", frozenset({456}))
    isolated.setattr(start_module, "clear_cache", cleared)
    message = _FakeMessage(_FakeBot(b""))

    asyncio.run(start_module.cmd_limpar(message))

    assert message.answers == [t(MSG_CACHE_CLEARED).format(count=3)]


# --- REQ-013: feedback --------------------------------------------------------


class _FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True


def test_feedback_without_text_keeps_waiting(isolated):
    state = _FakeState()
    sticker = _FakeMessage(_FakeBot(b""))

    asyncio.run(start_module.handle_feedback_text(sticker, state))

    assert sticker.answers == [t(MSG_FEEDBACK_TEXT_REQUIRED)]
    assert not state.cleared
    assert not (settings.temp_dir / "feedback.txt").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"document": _FakeDocument("doc.pdf", 10, "f")},
        {"photo": [SimpleNamespace(file_id="p")]},
        {"text": "/start"},
    ],
)
def test_a_file_or_command_ends_the_feedback_prompt_and_is_handled(isolated, kwargs):
    state = _FakeState()
    message = _FakeMessage(_FakeBot(b""), **kwargs)

    with pytest.raises(SkipHandler):
        asyncio.run(start_module.handle_feedback_text(message, state))

    assert state.cleared
    assert message.answers == []
    assert not (settings.temp_dir / "feedback.txt").exists()


def test_feedback_prompt_is_checked_before_the_commands():
    handlers = [handler.callback for handler in start_module.router.message.handlers]
    assert handlers[0] is start_module.handle_feedback_text


def test_feedback_text_is_recorded(isolated):
    state = _FakeState()
    message = _FakeMessage(_FakeBot(b""), text="Great descriptions")
    message.from_user = SimpleNamespace(id=456, username="reader")

    asyncio.run(start_module.handle_feedback_text(message, state))

    assert message.answers == [t(MSG_FEEDBACK_THANKS)]
    assert state.cleared
    assert "reader: Great descriptions" in (settings.temp_dir / "feedback.txt").read_text(encoding="utf-8")


# --- REQ-002: progress message ------------------------------------------------


def test_tracker_escapes_file_names_and_shows_progress():
    bot = _FakeBot(b"")
    tracker = StatusTracker(bot, 1, "my_<file>*.pdf")

    asyncio.run(tracker("Exporting HTML", percent=40))
    asyncio.run(tracker("Exporting HTML", percent=40))

    assert "my_&lt;file&gt;*.pdf" in bot.sent[0]
    assert "40%" in bot.sent[0]
    # An identical update is not re-sent (Telegram rejects no-op edits).
    assert bot.edited == []


# --- REQ-018: rate-limit retry -----------------------------------------------


def _retry_after(seconds):
    return TelegramRetryAfter(
        method=SendMessage(chat_id=1, text="x"), message="Too Many Requests", retry_after=seconds
    )


def test_rate_limited_requests_are_retried_within_bounds():
    waits = []
    calls = []

    async def sleep(seconds):
        waits.append(seconds)

    async def make_request(bot, method):
        calls.append(method)
        if len(calls) < 3:
            raise _retry_after(2)
        return "ok"

    middleware = RetryAfterMiddleware(max_retries=3, sleep=sleep)

    assert asyncio.run(middleware(make_request, None, SendMessage(chat_id=1, text="x"))) == "ok"
    assert waits == [2, 2]


def test_rate_limit_gives_up_after_the_bounded_policy():
    async def sleep(seconds):
        return None

    async def make_request(bot, method):
        raise _retry_after(1)

    middleware = RetryAfterMiddleware(max_retries=2, sleep=sleep)

    with pytest.raises(TelegramRetryAfter):
        asyncio.run(middleware(make_request, None, SendMessage(chat_id=1, text="x")))


def test_flood_wait_longer_than_the_cap_fails_fast():
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    async def make_request(bot, method):
        raise _retry_after(600)

    middleware = RetryAfterMiddleware(max_wait_seconds=60, sleep=sleep)

    with pytest.raises(TelegramRetryAfter):
        asyncio.run(middleware(make_request, None, SendMessage(chat_id=1, text="x")))
    assert waits == []


def test_settings_parse_operator_ids():
    from backend.config.settings import _int_ids_from_env

    assert _int_ids_from_env(" 12, x, ,34 ") == frozenset({12, 34})
    assert _int_ids_from_env("") == frozenset()

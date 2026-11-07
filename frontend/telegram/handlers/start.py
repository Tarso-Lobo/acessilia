import html
import shutil
from datetime import datetime

from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import LOG_TELEGRAM_FEEDBACK_RECEIVED
from backend.services.cache import clear_cache
from backend.tools.logger import logger
from backend.tools.validators import MSG_INVALID_EMAIL_ADDRESS, is_email_address_allowed
from frontend.clients.api_client import ApiError
from frontend.clients import default_client
from frontend.telegram import user_context
from frontend.telegram.access import is_operator
from frontend.telegram.middlewares.pause_middleware import get_paused_chats
from frontend.telegram.messages import (
    MSG_BOT_PAUSED,
    MSG_BOT_RESUMED,
    MSG_CACHE_CLEARED,
    MSG_CANCEL_NO_TASK,
    MSG_EMAIL_CONFIGURED,
    MSG_EMAIL_HINT,
    MSG_FEEDBACK_PROMPT,
    MSG_FEEDBACK_TEXT_REQUIRED,
    MSG_FEEDBACK_THANKS,
    MSG_FORMATS_TEXT,
    MSG_HEALTH_ACTIVE_MODEL,
    MSG_HEALTH_API_ERROR,
    MSG_HEALTH_API_OFFLINE,
    MSG_HEALTH_API_STATUS,
    MSG_HEALTH_DISK_FREE,
    MSG_HEALTH_OVERALL_DEGRADED,
    MSG_HEALTH_OVERALL_OK,
    MSG_HEALTH_PROVIDER,
    MSG_HEALTH_QUEUE,
    MSG_HEALTH_REACHABLE,
    MSG_HEALTH_TEMP_MISSING,
    MSG_HEALTH_TEMP_OK,
    MSG_HEALTH_UNKNOWN,
    MSG_HEALTH_UNREACHABLE,
    MSG_HELP_TEXT,
    MSG_MODE_BAIXO_ON,
    MSG_MODE_DETAILED_ON,
    MSG_MODE_MEDIO_ON,
    MSG_MODE_NORMAL_ON,
    MSG_MODE_OCR_ON,
    MSG_NO_TASK_REGISTERED,
    MSG_OPERATOR_ONLY,
    MSG_START_TEXT,
    MSG_STATE_CANCELLED,
    MSG_STATE_CANCELLING,
    MSG_STATE_DONE,
    MSG_STATE_ERROR,
    MSG_STATE_PROCESSING,
    MSG_STATE_QUEUED,
    MSG_STATE_UNKNOWN,
    MSG_STATUS_SUMMARY,
    MSG_STATUS_TASK_NOT_FOUND,
    MSG_TASK_CANCEL_DONE,
    MSG_TASK_CANCEL_FAILED,
    MSG_TASK_CANCEL_REQUESTED,
)

router = Router()

client = default_client

#: Job states reported by the API, with the icon and the localized word /status shows for each (REQ-019).
_JOB_STATES: dict[str, tuple[str, str]] = {
    "queued": ("⏳", MSG_STATE_QUEUED),
    "processing": ("⏳", MSG_STATE_PROCESSING),
    "cancelling": ("⏳", MSG_STATE_CANCELLING),
    "done": ("✅", MSG_STATE_DONE),
    "error": ("❌", MSG_STATE_ERROR),
    "cancelled": ("🚫", MSG_STATE_CANCELLED),
}


#: Display order of the input extensions; any other configured extension follows alphabetically.
_INPUT_ORDER = (".pdf", ".docx", ".html", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")


def accepted_inputs() -> str:
    """List the extensions the service accepts, read from the same setting the API validates against (REQ-020).

    Returns:
        str: Upper-case extensions joined by commas, e.g. "PDF, DOCX, HTML, PNG".
    """
    allowed = {ext.lower() for ext in settings.allowed_extensions}
    ordered = [ext for ext in _INPUT_ORDER if ext in allowed]
    ordered += sorted(allowed - set(ordered))
    return ", ".join(ext.lstrip(".").upper() for ext in ordered)


class FeedbackStates(StatesGroup):
    waiting_feedback = State()


# Registered before every command so a pending feedback prompt sees the
# message first: a command or a file ends the prompt and is then handled
# normally, instead of the chat staying stuck waiting for feedback text.
@router.message(StateFilter(FeedbackStates.waiting_feedback))
async def handle_feedback_text(message: Message, state: FSMContext) -> None:
    """Persist the user's free-text feedback to a local log file and acknowledge it.

    A command, document or photo ends the feedback prompt and goes on to its
    own handler. Any other reply without text (a sticker, a voice note...) is
    not recorded: the user is asked for text and the prompt stays open.

    Args:
        message (Message): Aiogram Message holding the user's feedback text; no default (required).
        state (FSMContext): AIAGram FSM context that is cleared after the feedback is recorded (no default, aiogram-injected argument).
    """
    feedback = (message.text or "").strip()
    if feedback.startswith("/") or message.document or message.photo:
        await state.clear()
        raise SkipHandler()
    if not feedback:
        await message.answer(t(MSG_FEEDBACK_TEXT_REQUIRED))
        return

    user = message.from_user
    user_info = f"{user.username or user.id}" if user else "unknown"

    logger.info(t(LOG_TELEGRAM_FEEDBACK_RECEIVED).format(
        user_info=user_info, feedback=feedback
    ))

    feedback_file = settings.temp_dir / "feedback.txt"
    feedback_file.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().isoformat()
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {user_info}: {feedback}\n")

    await state.clear()
    await message.answer(t(MSG_FEEDBACK_THANKS))


@router.message(Command("email"))
async def cmd_email(message: Message) -> None:
    """Record the sender's e-mail for their next job in the current chat and topic.

    Args:
        message (Message): Incoming aiogram ``/email`` command carrying the address argument to store, or none when only the bare command was sent; no default (required).
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(t(MSG_EMAIL_HINT))
        return

    email = args[1].strip()
    if not is_email_address_allowed(email):
        await message.answer(f"{t(MSG_INVALID_EMAIL_ADDRESS)}\n{t(MSG_EMAIL_HINT)}")
        return
    user_context.user_emails[user_context.get_user_state_key(message)] = email
    await message.answer(t(MSG_EMAIL_CONFIGURED).format(email=html.escape(email)))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Greet the user and summarize accepted formats via /start using the active locale's start-text string.

    Args:
        message (Message): Incoming aiogram /start command; no default (required).
    """
    await message.answer(t(MSG_START_TEXT).format(inputs=accepted_inputs()))


@router.message(Command("ajuda"))
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """List every bot command available in the active locale via /ajuda or /help.

    Args:
        message (Message): Incoming aiogram help command; no default (required).
    """
    await message.answer(t(MSG_HELP_TEXT))


@router.message(Command("formatos"))
@router.message(Command("formats"))
async def cmd_formats(message: Message) -> None:
    """List accepted input containers and produced output formats via /formatos or its English alias /formats in the active locale.

    Args:
        message (Message): Incoming aiogram /formatos (or /formats) command; no default (required).
    """
    await message.answer(t(MSG_FORMATS_TEXT).format(inputs=accepted_inputs()))


@router.message(Command("ocr"))
async def cmd_ocr(message: Message) -> None:
    """
    Activate text-only OCR mode for the sender's next file in this chat and topic.

    Args:
        message (Message): Incoming aiogram /ocr command; no default (required).
    """
    user_context.user_modes[user_context.get_user_state_key(message)] = "ocr"
    await message.answer(t(MSG_MODE_OCR_ON))


@router.message(Command("detalhado"))
@router.message(Command("detailed"))
async def cmd_detailed(message: Message) -> None:
    """
    Activate maximum-detail mode for the sender's next file in this chat and topic.

    Args:
        message (Message): Incoming aiogram /detalhado (or /detailed) command; no default (required).
    """
    user_context.user_modes[user_context.get_user_state_key(message)] = "detalhado"
    await message.answer(t(MSG_MODE_DETAILED_ON))


@router.message(Command("medio"))
@router.message(Command("medium"))
async def cmd_medium(message: Message) -> None:
    """
    Activate medium-detail mode for the sender's next file in this chat and topic.

    Args:
        message (Message): Incoming aiogram /medio (or /medium) command; no default (required).
    """
    user_context.user_modes[user_context.get_user_state_key(message)] = "medio"
    await message.answer(t(MSG_MODE_MEDIO_ON))


@router.message(Command("baixo"))
@router.message(Command("low"))
async def cmd_low(message: Message) -> None:
    """
    Activate low-detail mode for the sender's next file in this chat and topic.

    Args:
        message (Message): Incoming aiogram /baixo (or /low) command; no default (required).
    """
    user_context.user_modes[user_context.get_user_state_key(message)] = "baixo"
    await message.answer(t(MSG_MODE_BAIXO_ON))


@router.message(Command("normal"))
async def cmd_normal(message: Message) -> None:
    """
    Activate normal mode (the medium default) for the sender's next file in this chat and topic.

    Args:
        message (Message): Incoming aiogram /normal command; no default (required).
    """
    user_context.user_modes[user_context.get_user_state_key(message)] = "medio"
    await message.answer(t(MSG_MODE_NORMAL_ON))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """
    Show the state, progress and stage of the task recorded for the sender in this chat and topic.

    Args:
        message (Message): Incoming aiogram /status command; no default (required).
    """
    task_id = user_context.user_task_ids.get(user_context.get_user_state_key(message))
    if not task_id:
        await message.answer(t(MSG_NO_TASK_REGISTERED))
        return
    try:
        status = await client.get_job_status(task_id)
    except ApiError as e:
        await message.answer(t(MSG_STATUS_TASK_NOT_FOUND).format(status_code=e.status_code))
        return
    pct = int((status.get("progresso") or 0.0) * 100)
    icon, state = _JOB_STATES.get(status.get("status", ""), ("❓", MSG_STATE_UNKNOWN))
    await message.answer(
        t(MSG_STATUS_SUMMARY).format(
            icon=icon,
            state=t(state),
            task_id=html.escape(task_id),
            filename=html.escape(str(status.get("arquivo") or "?")),
            pct=pct,
            stage=html.escape(str(status.get("etapa_atual") or "")),
        )
    )


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    """
    Report the API, AI provider, model, queue and local-resource checks to an operator (REQ-014, REQ-015).

    The summary line reads "degraded" whenever any check fails, so a failing
    service is never reported as healthy.

    Args:
        message (Message): Incoming aiogram /health command; no default (required).
    """
    if not is_operator(message):
        await message.answer(t(MSG_OPERATOR_ONLY))
        return

    checks: list[str] = []
    healthy = True
    unknown = t(MSG_HEALTH_UNKNOWN)

    try:
        health = await client.health()
        api_ok = health.get("status") == "ok"
        model_ok = bool(health.get("model_reachable"))
        healthy = api_ok and model_ok
        checks.append(
            t(MSG_HEALTH_API_STATUS).format(
                icon="✅" if api_ok else "⚠️",
                status=html.escape(str(health.get("status") or unknown)),
            )
        )
        checks.append(
            t(MSG_HEALTH_PROVIDER).format(
                icon="✅" if model_ok else "❌",
                provider=html.escape(str(health.get("model_client") or unknown)),
                state=t(MSG_HEALTH_REACHABLE if model_ok else MSG_HEALTH_UNREACHABLE),
            )
        )
        checks.append(
            t(MSG_HEALTH_ACTIVE_MODEL).format(
                model=html.escape(str(health.get("model_name") or unknown))
            )
        )
        if health.get("queue_size") is not None:
            checks.append(t(MSG_HEALTH_QUEUE).format(size=health["queue_size"]))
    except ApiError as e:
        healthy = False
        checks.append(
            t(MSG_HEALTH_API_ERROR).format(
                status_code=e.status_code, detail=html.escape(str(e.detail))
            )
        )
    except Exception as e:
        healthy = False
        checks.append(t(MSG_HEALTH_API_OFFLINE).format(error=html.escape(str(e))))

    temp_dir = settings.temp_dir
    if temp_dir.exists():
        checks.append(t(MSG_HEALTH_TEMP_OK))
    else:
        healthy = False
        checks.append(t(MSG_HEALTH_TEMP_MISSING))

    try:
        usage = shutil.disk_usage(temp_dir.anchor or "/")
        free_gb = usage.free / (1024**3)
        checks.append(t(MSG_HEALTH_DISK_FREE).format(free_gb=free_gb))
    except Exception:
        pass

    checks.append(t(MSG_HEALTH_OVERALL_OK if healthy else MSG_HEALTH_OVERALL_DEGRADED))
    await message.answer("\n".join(checks))


@router.message(Command("limpar"))
@router.message(Command("clear"))
async def cmd_limpar(message: Message) -> None:
    """
    Clear the local cache of processed-file artifacts for an operator and confirm how many entries were removed.

    Args:
        message (Message): Incoming aiogram /limpar (or its English alias /clear) command; no default (required).
    """
    if not is_operator(message):
        await message.answer(t(MSG_OPERATOR_ONLY))
        return
    count = await clear_cache()
    await message.answer(t(MSG_CACHE_CLEARED).format(count=count))


@router.message(Command("cancelar"))
@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    """
    Cancel the job tracked for the sender in this chat and topic.

    A job the API still has to stop ("cancelling") stays tracked, so /status
    keeps working and the upload's own poll reports when it ends.

    Args:
        message (Message): Incoming aiogram /cancelar (or its English alias /cancel) command; no default (required).
    """
    state_key = user_context.get_user_state_key(message)
    task_id = user_context.user_task_ids.get(state_key)
    if not task_id:
        await message.answer(t(MSG_CANCEL_NO_TASK))
        return
    try:
        result = await client.cancel_job(task_id)
    except ApiError as e:
        await message.answer(
            t(MSG_TASK_CANCEL_FAILED).format(
                status_code=e.status_code, detail=html.escape(str(e.detail))
            )
        )
        return
    cancelled_id = html.escape(str(result.get("task_id", task_id)))
    if result.get("status") == "cancelling":
        await message.answer(t(MSG_TASK_CANCEL_REQUESTED).format(task_id=cancelled_id))
        return
    user_context.user_task_ids.pop(state_key, None)
    await message.answer(t(MSG_TASK_CANCEL_DONE).format(task_id=cancelled_id))


@router.message(Command("desativar"))
@router.message(Command("deactivate"))
async def cmd_desativar(message: Message) -> None:
    """
    Pause bot processing for this chat until /ativar or /activate is used again.

    Args:
        message (Message): Incoming aiogram /desativar (or its English alias /deactivate) command; no default (required).
    """
    paused = get_paused_chats()
    paused.add(message.chat.id)
    await message.answer(t(MSG_BOT_PAUSED))


@router.message(Command("ativar"))
@router.message(Command("activate"))
async def cmd_ativar(message: Message) -> None:
    """
    Resume bot processing for this chat after a prior /desativar or /deactivate pause.

    Args:
        message (Message): Incoming aiogram /ativar (or its English alias /activate) command; no default (required).
    """
    paused = get_paused_chats()
    paused.discard(message.chat.id)
    await message.answer(t(MSG_BOT_RESUMED))


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    """
    Prompt the user to type their opinion of processing quality before entering a wait-for-text input state.

    Args:
        message (Message): Incoming aiogram /feedback command; no default (required).
        state (FSMContext): AIAGram FSM context used to transition into FeedbackStates.waiting_feedback after showing the prompt (no default, required aiogram-injected argument).
    """
    await state.set_state(FeedbackStates.waiting_feedback)
    await message.answer(t(MSG_FEEDBACK_PROMPT))

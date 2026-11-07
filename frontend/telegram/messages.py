"""
What this module provides: canonical English message ids (msgids) covering every user-facing text emitted by the
Telegram bot's general command handlers and the document/photo processing lifecycle handlers, a pt_BR translation
table mirroring each msgid for locale catalog generation,
and a per-locale mapping builder that scripts/gen_locale_catalogs consumes so adding another supported language later only
requires one additional entry in BOT_PT_TRANSLATIONS-style tables plus re-running catalog generation. Module-level constants
doube as the single source of truth that frontend/telegram/handlers/start.py formats at runtime through backend.i18n.t().

The bot sends every reply with Telegram's HTML parse mode, so the texts below use HTML tags (never Markdown), and
callers escape every value they substitute (file names, e-mails, API details, stage labels).
"""

from __future__ import annotations

#: Hint shown when /email is invoked without an address argument.
MSG_EMAIL_HINT: str = "Please provide an e-mail address: /email you@example.com"
#: Confirmation returned by /email once the deliver-to address has been recorded; {email} is substituted at call time.
MSG_EMAIL_CONFIGURED: str = (
    "E-mail {email} configured! Now send your document and it will be delivered to this e-mail address."
)
#: Welcome text emitted on /start explaining what the bot does; {inputs} is the accepted-extension list from settings.
MSG_START_TEXT: str = (
    "Hello! Send a PDF, image or scanned document."
    "\n\nYou'll get back an accessible version for screen readers."
    "\n\nAccepted formats: {inputs}"
    "\n\nSend /help to see every command."
)
#: Full catalog of bot commands emitted on /ajuda and /help; every section has a text heading so it reads without the emoji.
MSG_HELP_TEXT: str = (
    "Available commands:"
    "\n\n🔧 General:"
    "\n/start - Start the bot"
    "\n/help - Show this message"
    "\n/formats - List supported input and output formats"
    "\n\n🎨 Description modes (apply to your next file):"
    "\n/detailed - Maximum detail: typography, colors, layout, element positions"
    "\n/medium - Full text + clear image descriptions (default)"
    "\n/low - Content focused: full text extraction + concise image description (faster)"
    "\n/normal - Equivalent to /medium"
    "\n/ocr - Text extraction only, no visual description"
    "\n\n📨 Delivery:"
    "\n/email you@example.com - Also e-mail the result of your next file"
    "\n\n⚙️ Control:"
    "\n/status - Show the state and progress of your current task"
    "\n/cancel - Cancel your current task"
    "\n/deactivate - Disable the bot for this chat"
    "\n/activate - Re-enable the bot for this chat"
    "\n/feedback - Send your opinion about processing quality"
    "\n\n🛠️ Operators only:"
    "\n/health - Check system health (API, AI provider, model, disk)"
    "\n/clear - Clear the processing cache"
    "\n\nJust send a file and I'll process it automatically."
)
#: /formatos answer; {inputs} is the accepted-extension list from settings (what the API validates against), then
#: every output the service actually puts in the package
#: (backend/api/worker.py: TXT and HTML always; DOCX, PDF/UA and MP3 when their optional export succeeds; a ZIP of all).
MSG_FORMATS_TEXT: str = (
    "Accepted input formats:"
    "\n• {inputs}"
    "\n• Photos sent directly in Telegram"
    "\n\n"
    "Output formats in the accessible package:"
    "\n• Structured TXT"
    "\n• Semantic HTML"
    "\n• Accessible DOCX (optional)"
    "\n• Tagged PDF/UA (optional)"
    "\n• MP3 audio narration (optional)"
    "\n• ZIP with every generated file"
    "\n\nOptional formats are only included when they are generated successfully;"
    " the completion message lists what your package actually contains."
)

# --- File/photo processing lifecycle messages (frontend/telegram/handlers/document.py) ---
#: Confirmation shown right after the user sends a document file.
MSG_FILE_RECEIVED: str = "📄 File received!"
#: Confirmation shown right after the user sends a photo.
MSG_PHOTO_RECEIVED: str = "📷 Photo received!"
#: Line appended to the receipt naming the description mode the file is submitted with; {mode} is a localized mode name.
MSG_SUBMITTED_WITH_MODE: str = "Description mode: {mode}"
#: Localized description-mode names substituted into MSG_SUBMITTED_WITH_MODE.
MSG_MODE_NAME_DETAILED: str = "detailed"
MSG_MODE_NAME_MEDIUM: str = "medium (default)"
MSG_MODE_NAME_LOW: str = "low"
MSG_MODE_NAME_OCR: str = "OCR (text only)"
#: Progress line emitted while the bot downloads the attachment from Telegram servers into local storage.
MSG_DOWNLOADING_FILE: str = "Downloading file..."
#: Error reply when Telegram does not hand the uploaded file over (missing, expired or unreadable upload).
MSG_FILE_DOWNLOAD_FAILED: str = "❌ Could not download your file from Telegram. Please send it again."
#: Error reply returned when the processing API rejects the submitted job; {status_code}/{detail} substituted at call time.
MSG_SUBMIT_FAILED: str = (
    "❌ Error submitting the file for processing ({status_code}): {detail}"
)
#: Reply sent when the local bot cannot reach the processing server at all (network or start-up failure).
MSG_CONTACT_SERVER_FAILED: str = "❌ Could not contact the processing server. Try again."
#: Progress line emitted once a job has been accepted by the API and is waiting in the queue; {task_id} substituted at call time.
MSG_TASK_ENQUEUED: str = "Task {task_id} queued..."
#: Reply emitted when the job lands behind other jobs in the single processing lane; {position} substituted at call time.
MSG_QUEUE_POSITION: str = "⏳ You are in the queue (Position: {position})."
#: Polling progress line shown while a job is still queued; {step} is the current pipeline stage label reported by the API and may be empty.
MSG_WAITING_IN_QUEUE: str = "Waiting in queue... {step}"
#: Receipt emitted when the download link has also been e-mailed to the address stored via /email; {email} substituted at call time.
MSG_DOWNLOAD_LINK_EMAILED: str = "✅ Download link sent to {email}!"
#: Notice emitted when the service reports that e-mailing the result failed; {email} substituted at call time.
MSG_EMAIL_DELIVERY_FAILED: str = (
    "⚠️ Could not e-mail the result to {email}. Use the download link above."
)
#: Notice emitted when the service has not confirmed the e-mail delivery within the bot's wait; {email} substituted at call time.
MSG_EMAIL_DELIVERY_UNCONFIRMED: str = (
    "ℹ️ E-mail delivery to {email} has not been confirmed yet. Use the download link above."
)
#: Completion reply carrying the download URL; {days} is the link validity and {url} the link itself.
MSG_ACCESSIBLE_PACKAGE_READY: str = (
    "✅ Accessible package generated!\n\n📥 Download link (valid for {days} days):\n{url}"
)
#: Line appended to the completion reply listing the formats the package really holds; {formats} is a comma-separated list.
MSG_PACKAGE_CONTENTS: str = "Package contents: {formats}"
#: Warning appended when optional exports failed; {formats} names the missing formats (e.g. "PDF/UA, MP3").
MSG_PACKAGE_OPTIONAL_MISSING: str = (
    "⚠️ These optional formats could not be generated and are not in the package: {formats}"
)
#: Warning appended when the service reported warnings the bot cannot map to a specific format.
MSG_PACKAGE_WARNINGS: str = (
    "⚠️ The service reported warnings for this conversion; some optional formats may be missing from the package."
)
#: Reply when the service marks a job as done but provides no download link, so nothing can be delivered.
MSG_DONE_WITHOUT_LINK: str = (
    "❌ The service finished the task but did not provide a download link, so the package cannot be delivered. "
    "Please try again."
)
#: Generic error reply returned when an unexpected exception interrupts file processing mid-flight.
MSG_PROCESSING_ERROR_GENERIC: str = "❌ Error processing the file. Try again."
#: Base text used for API-reported job failures; localized failure detail lines are appended by the caller after lookup so each language keeps its own wording around them.
MSG_PROCESS_FAILED_BASE: str = "❌ Processing error."
#: Reply emitted when a running job is cancelled (e.g., via /cancel).
MSG_TASK_CANCELLED: str = "🚫 Task cancelled."
#: Time-out reply shown when the bot waited through settings.request_timeout without completing; directs users to /status to check progress.
MSG_PROCESSING_TIMEOUT: str = (
    "⏰ Processing took longer than expected. Use /status to follow progress."
)

# --- start.py command responses (frontend/telegram/handlers/start.py) ---
#: Reply for /ocr; confirms text-only extraction mode is active.
MSG_MODE_OCR_ON: str = (
    "📄 OCR Mode On!\n\nSend a PDF or image and I shall extract ONLY the written text, without visual description."
)
#: Reply for /detalhado (detailed); confirms maximum-detail description mode is active.
MSG_MODE_DETAILED_ON: str = (
    "🔍 Detailed Mode On!\n\n" +
    "Description at the highest detail level: typography, spacing, colors, layout, element positions and a professional image description."
)
#: Reply for /medium; confirms standard mode.
MSG_MODE_MEDIO_ON: str = (
    "📋 Medium Mode on!\n\nFull text plus clear image descriptions. Ideal for most documents."
)
#: Reply for /low; confirms content-focused, faster mode.
MSG_MODE_BAIXO_ON: str = (
    "⚡ Low Mode on!\n\nFocused on content: the full text extracted and a concise description of images. Faster."
)
#: Reply for /normal; confirms equivalence to medium mode.
MSG_MODE_NORMAL_ON: str = (
    "📋 Normal Mode on (equivalent to Medium).\n\nFull text plus clear image descriptions."
)
#: Status reply when no job has been recorded in this chat yet (/status, /cancelar).
MSG_NO_TASK_REGISTERED: str = "No task registered in this chat yet."
#: Status error reply; {status_code} is the rejected HTTP code.
MSG_STATUS_TASK_NOT_FOUND: str = "❌ Task not found in API ({status_code})."
#: Successful status summary for /status; {state} is a localized state word so the reply never depends on {icon} alone;
#: {task_id}, {filename}, {pct} and {stage} come from the API response.
MSG_STATUS_SUMMARY: str = (
    "{icon} {state}\nTask: <code>{task_id}</code>\nFile: {filename}\nProgress: {pct}%\nStage: {stage}"
)
#: Localized job-state words used by /status (REQ-019: state is readable without the emoji).
MSG_STATE_QUEUED: str = "Queued"
MSG_STATE_PROCESSING: str = "Processing"
MSG_STATE_CANCELLING: str = "Cancelling"
MSG_STATE_DONE: str = "Completed"
MSG_STATE_ERROR: str = "Failed"
MSG_STATE_CANCELLED: str = "Cancelled"
MSG_STATE_UNKNOWN: str = "Unknown state"
#: Health check line for Ollama online state; {model_count} is the number of locally loaded models.
MSG_OLLAMA_ONLINE: str = "✅ Ollama: online ({model_count} model(s))"
#: Health warning when Ollama answered off nominal HTTP 200; {code} substituted at call time with observed code.
MSG_OLLAMA_UNEXPECTED: str = "⚠️ Ollama: unexpected answer ({code})"
#: Health check line for Ollama being unreachable; {error} substituted with exception text from the health probe.
MSG_OLLAMA_OFFLINE: str = "❌ Ollama: offline ({error})"
#: Health check line stating which llm model is active; {model} substituted at call time.
MSG_HEALTH_ACTIVE_MODEL: str = "🤖 Model: {model}"
#: Health line for the API itself; {icon} and {status} come from the API's /health answer.
MSG_HEALTH_API_STATUS: str = "{icon} API: {status}"
#: Health line when the API answered /health with an HTTP error; {status_code}/{detail} substituted at call time.
MSG_HEALTH_API_ERROR: str = "❌ API: error {status_code} ({detail})"
#: Health line when the API could not be reached at all; {error} is the connection error text.
MSG_HEALTH_API_OFFLINE: str = "❌ API: offline ({error})"
#: Health line for the AI provider; {provider} is the configured client and {state} a localized reachability word.
MSG_HEALTH_PROVIDER: str = "{icon} AI provider: {provider} ({state})"
#: Reachability words for MSG_HEALTH_PROVIDER.
MSG_HEALTH_REACHABLE: str = "reachable"
MSG_HEALTH_UNREACHABLE: str = "unreachable"
#: Health line with the API's queue length; {size} substituted at call time.
MSG_HEALTH_QUEUE: str = "📋 Queue: {size} job(s)"
#: Value shown when the API omits a health field.
MSG_HEALTH_UNKNOWN: str = "unknown"
#: Health summary when every check passed.
MSG_HEALTH_OVERALL_OK: str = "Overall: healthy."
#: Health summary when at least one check failed, so the reply never reads as healthy.
MSG_HEALTH_OVERALL_DEGRADED: str = "Overall: degraded, at least one check failed."
#: Temp directory health probe result when the settings.temp_dir path exists.
MSG_HEALTH_TEMP_OK: str = "✅ Temp dir: ok"
#: Temp directory health probe notice when the settings.temp_dir path does not exist.
MSG_HEALTH_TEMP_MISSING: str = "⚠️ Temp dir: missing"

#: Tracker progress message displayed when document conversion finishes successfully.
MSG_STATUS_CONVERSION_DONE: str = "✅ Conversion complete!"
#: Tracker fallback text shown when the processing job ends in an error; generic wording intentionally avoids leaking exception details to chat users.
MSG_STATUS_PROCESSING_FAILED: str = ("❌ Error during processing.")



#: Cache cleared reply; {count} is the number of files deleted from cache storage.
MSG_CACHE_CLEARED: str = ("🧹 Cache cleared! {count} file(s) removed.")
#: Reply to /health or /clear from a user who is not listed in TELEGRAM_ADMIN_IDS.
MSG_OPERATOR_ONLY: str = "⛔ This command is restricted to the bot operators."
#: Disk free space probe line; {free_gb} is formatted at call time with one decimal.
MSG_HEALTH_DISK_FREE: str = "💾 Free disk: {free_gb:.1f} GB"
#: /status reply when the chat has no recorded processing task yet.
MSG_STATUS_NO_TASK: str = "No task in this chat."
#: /cancelar reply when there is nothing to cancel in this chat.
MSG_CANCEL_NO_TASK: str = "No active task in this chat to cancel."
#: Reply emitted after a successful job cancellation; {task_id} substituted at call time with the cancelled job's id.
MSG_TASK_CANCEL_DONE: str = "✅ Task {task_id} cancelled."
#: Reply when the API accepted the cancellation but the running job still has to stop; {task_id} substituted at call time.
MSG_TASK_CANCEL_REQUESTED: str = (
    "⏳ Cancellation of task {task_id} requested. I'll let you know when it stops."
)
#: /cancelar error reply when the API rejects the cancellation request; {status_code}/{detail} are the API response fields, substituted at call time.
MSG_TASK_CANCEL_FAILED: str = ("❌ Could not cancel the task ({status_code}): {detail}")
#: Reply shown by /deactivate confirming the bot is paused for this chat.
MSG_BOT_PAUSED: str = "Bot disabled in this chat. Use /activate to re-enable it."
#: Reply shown by /activate confirming the bot has been re-enabled for this chat; invites user to send a document.
MSG_BOT_RESUMED: str = ("Bot re-enabled! Send me a document to get started.")
#: Prompt text emitted when the user invokes /feedback, instructing them how to write their opinion of processing quality before entering input state.
MSG_FEEDBACK_PROMPT: str = (
    "📝 <b>Send Feedback</b>\n\n"
    "Type your opinion on processing quality, improvement suggestions or issues you encountered.\n\n"
    "Example:\n"
    '\"The image description came out great but the extracted text had a few errors."\n\n'
    "Your feedback is very important to us!"
)
#: Reply when the user answers the feedback prompt with something other than text (a file, a sticker...).
MSG_FEEDBACK_TEXT_REQUIRED: str = (
    "Please send your feedback as a text message, or send any command to do something else."
)
#: Confirmation emitted once the user's feedback message has been recorded and logged; thanks them for contributing.
MSG_FEEDBACK_THANKS: str = ("✅ Feedback received! Thanks for your contribution.")

# Batch A planning/validation failure templates, registered alongside the part-5 entries above so catalog
# completeness checks keep requiring non-empty pt_BR translations plus matching en_US identity pairs until the i18n effort for this branch is complete.
#: PlanStep.validate_parameters failing on an execute-obligation action missing any of obligation_id / obligation_kind / method.
MSG_EXECUTE_OBLIGATION_MISSING_FIELDS: str = ("The execute-obligation action requires obligation_id, obligation_kind and method")
#: PlanStep.validate_parameters failing when a non-execution plan step still carries execution parameter values for {action}.
MSG_ACTION_REJECTS_EXECUTION_PARAMETERS: str = ("{action} does not accept obligation or method parameters")
#: NominalPlan.validate_plan failure when step indices are not zero-based and contiguous whole numbers in order.
MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO: str = ("Plan step indices must be contiguous whole numbers starting at zero")
#: NominalPlan.validate_plan failure when the final plan step is missing the mandatory complete-job termination action for a nominal plan.
MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB: str = ("A nominal plan must end with the complete-job action")
#: NominalPlan.validate_plan failure comparing declared expected_total_cost field {declared} to summed per-step expected cost total of {calculated} in an unequal check for the two values.
MSG_EXPECTED_TOTAL_COST_MISMATCH: str = ("Declared expected_total_cost={declared}; plan steps sum to expected cost {calculated}")
#: NominalPlan.validate_plan failure when a planned execute-obligation step has no corresponding entry in selected_obligations.
MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION: str = ("A nominal plan contains an obligation that was not selected")
#: PlannerOutcome validate_outcome requiring all plan content fields to be present for status==solved results per {message} below at the raise site in planning/models.py in the code change accompanying this constant. Used for a solved result lacking at least one of plan file, identifier or statistics content.
MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS: str = (
    "A solver outcome marked as ended before execution began cannot carry plan details"
)
#: Outcome validation requiring the recorded run to have been validated and accepted after solving for a result that claims solved status without successful validator pass recorded alongside it.
MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION: str = ("Marking a planner outcome as solved requires its computed solution to have passed validation")
#: Prohibiting any error record field from being present on an otherwise-validated successful solver run result in PlannerOutcome validate_outcome for status==solved branches.
MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR: str = ("Solving a planner outcome cannot also hold recorded error information")
#: Require both fields present when recording a run that reported no solution found at PlannerOutlet's validation site in Planning/Model.Py for a result claiming failed status without any diagnostic content attached at all.
MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR: str = ("A planner outcome marked as failed requires an error type and message")
#: Forbid marking computed results both validated-and-passed while simultaneously flagged as having failed validation when the run finished solving successfully in a failed-status branch check on the same PlannerOutcome record during validate_outcome.
MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION: str = ("A planner outcome marked as failed cannot simultaneously record successful validation")
#: Requires both planned execution backends listed in outcomes mapping for PlanningComparison.validate_report domain-level consistency check comparing planner identities against recorded backend keys; raise message text shown to users / developers reading the generated JSON comparison result report body.
MSG_COMPARISON_REQUIRES_BOTH_BACKENDS: str = ("Planning comparisons must contain results from both the internal planner and Fast Downward")
#: Outcome key mismatch guard on each backend, result pair in that mapping for {key} expecting {backend_name}; raise message text shown to users / developers reading validation context after a comparison report builds successfully with divergent identifiers attached elsewhere in its metadata fields as well.
MSG_COMPARISON_OUTCOME_KEY_MISMATCH: str = ("Outcome key {key} does not match recorded planner backend {backend}")
#: A normalized description for the planning-comparison JSON schema document, localized alongside every other user-visible string in this branch's i18n effort so tooling inspecting or rendering schema metadata can rely on catalog-driven localization rather than hardcoded strings; variable substituted at call time via t() like all other part-6 entries.
MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION: str = ("Normalized comparison between the internal planner and Fast Downward executions of one planning problem")
#: A normalized description for the nominal-plan JSON schema document, localized so tooling inspecting or rendering its metadata reads catalog-driven text; variable substituted at call time via t() like all other part-6 entries.
MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION: str = ("Nominal plan derived from the processing manifest and PDDL domain of Acessilia; effects are confirmed only after executed by an executor")







#: Requires MethodResult to have been marked validated before claiming success; raise message text for that guard in backend.core.execution.models.MethodResult.success_requires_validation domain validation.
MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION: str = ("A method result claimed as successful must also have passed its validation gate")
#: Duplicate artifact identifier guard across the artifacts mapping on MethodResult, one per unique id expected; raise message text shown to users / developers reading that model's own pydantic validation context.
MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS: str = ("The method result contains duplicate artifact identifiers")
#: A normalized description for the execution-report JSON schema document, localized alongside every other user-visible string in this branch's i18n effort so tooling inspecting or rendering schema metadata can rely on catalog-driven localization rather than hardcoded strings; variable substituted at call time via t() like all other part-6 entries.
MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION: str = ("Report of the execution of a nominal plan over one manifest, with per-step method results and collected artifacts")

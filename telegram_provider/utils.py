import asyncio
import contextlib
import time
from collections import deque
from datetime import date, timedelta
from threading import Lock
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from telegram import Message
from telegram.error import BadRequest, RetryAfter

from operation.enums import VehicleStatus
from operation.models import VehicleLine
from spotting.models import Event
from telegram_provider.enums import MessageDirection
from telegram_provider.models import TelegramLogs

if TYPE_CHECKING:
    from telegram.ext import Application


class TelegramBotNotReady(RuntimeError):
    """A usable PTB ``Application`` could not be obtained.

    Raised when ``TELEGRAM_BOT_TOKEN`` is not configured and no
    application was started by the ASGI lifespan, so governed egress has
    nothing to send with.
    """


async def get_ptb_application() -> "Application":
    """Return the PTB application, lazily building one when possible.

    Resolution order:

    1. The module global in ``telegram_provider.apps``, when the ASGI
       lifespan already started the application.
    2. A lazily built application (``initialize()`` + ``start()``, no
       webhook — registering that remains the ASGI server's job) so
       Celery workers, which never run the lifespan, can still send.

    The import is function-local on purpose: it reads the CURRENT value
    of the module global, which the ASGI startup signal rebinds. An
    import-time binding would capture the initial ``None`` forever (the
    documented import-time-binding bug).

    Accepted benign race: two concurrent first-callers may each build an
    app; last-writer-wins caches the global and the loser is
    garbage-collected — harmless at digest scale.
    """
    from telegram.ext import Application

    import telegram_provider.apps as apps_module

    if apps_module.ptb_application is not None:
        return apps_module.ptb_application

    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramBotNotReady(
            "TELEGRAM_BOT_TOKEN is not configured and no PTB Application "
            "was started by the ASGI lifespan; cannot send Telegram "
            "messages."
        )

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).updater(None).build()
    await app.initialize()
    await app.start()
    apps_module.ptb_application = app
    return app


class PerChatRateLimiter:
    """Thread-safe in-process sliding-window rate limiter, per chat.

    Allows at most ``max_per_window`` sends per rolling ``window_seconds``
    for each chat. :meth:`acquire` never blocks and never holds the lock
    across an await: it either records the call and returns ``0.0``, or
    returns the number of seconds to sleep before the next slot opens.
    """

    def __init__(self, max_per_window: int = 30, window_seconds: float = 1.0) -> None:
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds
        self._lock = Lock()
        self._timestamps: dict[int | str, deque[float]] = {}

    def acquire(self, chat_id: int | str) -> float:
        now = time.monotonic()
        window_start = now - self._window_seconds
        with self._lock:
            timestamps = self._timestamps.setdefault(chat_id, deque())
            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()
            if len(timestamps) >= self._max_per_window:
                return max(self._window_seconds - (now - timestamps[0]), 0.0)
            timestamps.append(now)
            return 0.0


rate_limiter = PerChatRateLimiter()

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0


def _json_serializable_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter kwargs down to JSON-serializable primitives for audit storage."""
    return {
        key: value
        for key, value in kwargs.items()
        if value is None or isinstance(value, str | int | float | bool)
    }


async def send_message(chat_id: int | str, text: str, **kwargs: Any) -> Message | None:
    """Send a Telegram message through governed egress.

    Writes one OUTBOUND ``TelegramLogs`` audit row up front, then attempts
    delivery with bounded retries (exponential backoff, honoring PTB's
    ``RetryAfter`` delay). On success the row is stamped with ``sent_at``;
    once retries are exhausted the row keeps ``sent_at=None`` as the
    dead-letter record and the admin chat receives a best-effort direct
    notification. Returns the sent ``Message``, or ``None`` on failure.
    """
    app = await get_ptb_application()
    log = await TelegramLogs.objects.acreate(
        direction=MessageDirection.OUTBOUND,
        payload={
            "chat_id": chat_id,
            "text": text,
            **_json_serializable_kwargs(kwargs),
        },
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rate_delay = rate_limiter.acquire(chat_id)
            if rate_delay > 0:
                await asyncio.sleep(rate_delay)
            message = await app.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as exc:  # boundary: every provider failure is audited
            log.retry_count = attempt
            log.last_error = f"{type(exc).__name__}: {exc}"
            await log.asave()
            if attempt == MAX_RETRIES:
                break
            backoff = BACKOFF_BASE_SECONDS**attempt
            if isinstance(exc, RetryAfter):
                retry_after = exc.retry_after
                if isinstance(retry_after, timedelta):
                    retry_after = retry_after.total_seconds()
                backoff = retry_after
            await asyncio.sleep(backoff)
        else:
            log.sent_at = timezone.now()
            log.retry_count = attempt - 1
            await log.asave()
            return message

    # Dead-lettered (sent_at stays None). Best-effort admin ping — a direct
    # bot call, deliberately NOT recursing into send_message.
    if settings.TELEGRAM_ADMIN_CHAT_ID:
        with contextlib.suppress(Exception):
            await app.bot.send_message(
                chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
                text=(
                    f"[rosak] Telegram send failed after {MAX_RETRIES} attempts "
                    f"to chat {chat_id}: {log.last_error}"
                ),
            )
    return None


async def retry_on_error(
    source_obj: Any,
    fn_name: str,
    *args: Any,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    **kwargs: Any,
) -> Any:
    """Call ``source_obj.fn_name`` with bounded retries and backoff.

    Retries at most ``max_retries`` times, sleeping ``backoff_base **
    attempt`` seconds between attempts. ``BadRequest("Message to react not
    found")`` is terminal success — the reacted message is simply gone.
    Returns ``None`` immediately when ``source_obj`` is ``None``; re-raises
    the last exception once retries are exhausted.
    """
    if source_obj is None:
        return None

    for attempt in range(1, max_retries + 1):
        try:
            return await getattr(source_obj, fn_name)(*args, **kwargs)
        except BadRequest as exc:
            if "Message to react not found" in exc.message:
                return None
            if attempt == max_retries:
                raise
        except Exception:
            if attempt == max_retries:
                raise
        await asyncio.sleep(backoff_base**attempt)
    return None


def get_daily_updates(line_id: int, spotting_date: date | None = None) -> str:
    spotted_today_vehicle_ids = (
        Event.objects.filter(spotting_date=spotting_date or date.today())
        .distinct("vehicle")
        .values_list("vehicle_id", flat=True)
    )

    query_prefix = (
        VehicleLine.objects.select_related("vehicle")
        .filter(
            Q(line_id=line_id),
            ~Q(
                vehicle__status__in=[
                    VehicleStatus.MARRIED,
                    VehicleStatus.DECOMMISSIONED,
                ]
            ),
        )
        .order_by("vehicle__identification_no")
    )

    base_criteria = Q(vehicle__id__in=spotted_today_vehicle_ids)
    no_review_criteria = Q(vehicle__status__in=[VehicleStatus.IN_SERVICE])
    sections_criteria = {
        "Not Spotted": ~base_criteria,
        "Spotted Today": base_criteria & no_review_criteria,
        "Spotted Today, to review": base_criteria & ~no_review_criteria,
    }

    output_str_arr = [
        f"<b><u>{date.today().isoformat()}</u></b>",
        "",
    ]

    for title, criteria in sections_criteria.items():
        output_str_arr.append(f"<u>{title}</u>")
        results = query_prefix.filter(criteria)

        output_str_arr.append(
            ", ".join(x.vehicle.identification_no for x in results)
            if results
            else "<i>None</i>"
        )
        output_str_arr.append("")

    return "\n".join(
        [
            *output_str_arr,
            "",
            "",
            '<i>* Does not include vehicles marked "Decommissioned" or "Married"</i>',
        ]
    )

# Feature 2: One Governed Egress Path for All Outbound Messaging

> **Status (checked 2026-10-21): largely built.** Phases 1-2 and the data-model
> changes are in code. Built: `send_message` in `telegram_provider/utils.py` (one
> OUTBOUND `TelegramLogs` row per send, 3 attempts with exponential backoff, 30
> msgs/s per chat, keyword-only `return_log`); `retry_count` / `last_error` /
> `sent_at`; lazy PTB resolution; `error_handler` and admin pings via
> `TELEGRAM_ADMIN_CHAT_ID`; `report_spotting_today` on the helper; and
> `infinite_retry_on_error` removed.
> Open: (1) no dead-letter queue; exhausted sends remain as `sent_at IS NULL` rows.
> (2) The rate limiter is in-process, so it is per worker, not shared across workers.
> (3) `telegram_provider/views.py` still binds `ptb_application` at import time.
> (4) `error_handler` sends full update and user data to the admin chat, with no
> redaction. (5) Phase 4 is partly done: `incident/tasks.py` announces official posts
> via `send_message`. Phase 5 (badges) is not started.

## Feature Overview

**Problem** (original; now largely resolved, see Status): Outbound Telegram was
ungoverned. There was no single owner for sending messages to users and channels;
every caller either reached around `telegram_provider`'s PTB application or
duplicated its plumbing:

- `spotting.tasks.report_spotting_today` sent digests outside the governed
  path — it instantiated its **own** `telegram.Bot` instead of reusing the PTB
  `Application` and its managed `httpx` client. *(Resolved: it now calls `send_message`.)*
- `telegram_provider.models.TelegramLogs.direction` has an `OUTBOUND` member
  (`MessageDirection.OUTBOUND = 1`) that was **never written** — the model's comment
  read `# TODO: We only record inbound for now`. There was no delivery audit trail
  for anything we sent. *(Resolved: `send_message` writes these rows.)*
- `telegram_provider.handlers.error_handler` only `print`ed its error report; the
  developer-DM `send_message` was commented out, so persistent failures were silently
  dropped. *(Resolved: it also sends to `TELEGRAM_ADMIN_CHAT_ID`.)*
- `settings.TELEGRAM_ADMIN_CHAT_ID` was declared and never consumed. *(Resolved:
  consumed by `send_message` and `error_handler`.)*
- `telegram_provider.utils.infinite_retry_on_error` retried unbounded with 10s
  sleeps, so a single stuck message could pin a Celery worker indefinitely. *(Resolved:
  removed. `docs/APPS.md` still lists it as a trap.)*

**Value**: A single owner for outbound messaging — one helper that every caller
goes through — with delivery logging, bounded retry, and shared rate limiting.
This is a reliability feature in its own right: it makes sends auditable, makes
failure handling deterministic, and prevents worker pinning.

**Prerequisite for**: Badge announcements (mlptf), incident alerts, and
per-user digests (Feature 3). All three need to send targeted messages to
individuals or channels, and none should be trusted to implement its own
Telegram plumbing. They inherit auditability, retry, and rate limiting for free
from this feature.

## Current State Analysis

- **`telegram_provider.apps`**: Owns the PTB `Application`. It is stored in a
  module-global `ptb_application`, built with `.updater(None)` (polling
  disabled), and initialized/started during ASGI lifespan
  (`ASGILifespanSignalHandler.startup`); `get_ptb_application()` builds one lazily
  when none exists (Celery workers). The managed `httpx.AsyncClient` is created in
  `startup` and closed in `shutdown`, but still no handler consumes it. `handlers_dict`
  registers `CommandHandler`s (inbound `/`-commands), and a `MessageHandler` routes
  media uploads to `media`.
- **`telegram_provider.handlers`**: Inbound command handlers (`ping`, `help`,
  `dadjoke`, `verify`, `help_spotting`, `delete`, `spot`/`s`, `spotting_today`,
  `fav`, `link`, `deletelink`, `approve`) plus `media`. `error_handler` builds an
  HTML error report, `print`s it, and sends it to `TELEGRAM_ADMIN_CHAT_ID` via
  `send_message`.
- **`telegram_provider.views`**: `TelegramInbound` webhook view — writes
  `TelegramLogs(direction=INBOUND)` then forwards the update to
  `ptb_application.process_update(...)`. It binds `ptb_application` at import
  time (known WSGI caveat, see Dependencies & Blockers).
- **`telegram_provider.models.TelegramLogs`**: `direction`, `payload`,
  `retry_count`, `last_error`, `sent_at` (migration `0004`). `send_message` writes
  `OUTBOUND` rows.
- **`telegram_provider.enums.MessageDirection`**: `INBOUND = 0`, `OUTBOUND = 1`.
- **`telegram_provider.utils`**: `send_message` (governed egress),
  `retry_on_error` (bounded; re-raises on exhaustion), `PerChatRateLimiter`,
  `get_ptb_application`, and `get_daily_updates` (renders the digest HTML).
  `infinite_retry_on_error` is gone.
- **`spotting.tasks.report_spotting_today`**: Nightly digest task. Now calls
  `telegram_provider.utils.send_message` via `async_to_sync`. Scheduled in
  `rosak/celery.py`'s `beat_schedule` at `crontab(hour="0", minute="0")`.
- **`common.tasks`**: General Celery work (NSFW moderation, media conversion,
  verification-code cleanup). Does **not** contain `infinite_retry_on_error` —
  that lives in `telegram_provider.utils`.

> **Note on drift (resolved)**: `docs/APPS.md` still describes `report_spotting_today`
> as instantiating its own `telegram.Bot`. That text is stale: the task now routes
> through `send_message`.

## Technical Requirements

### Backend Changes (rosak_backend)

#### 1. `telegram_provider` app (done)

- Add a `send_message(chat_id, text, *, return_log=False, **kwargs)` helper in
  `telegram_provider/utils.py` (done; `return_log` is an opt-in extra).
  - Uses the PTB `Application`'s bot instance and the managed `httpx` client
    (no new `Bot`, no new client).
  - Logs every attempt to `TelegramLogs` with `direction=OUTBOUND`.
  - Implements bounded retry — max 3 attempts, exponential backoff.
  - Respects rate limits (30 messages/second per chat).
- Keep all existing `CommandHandler`s intact.

#### 2. `spotting` app (done)

- Refactor `report_spotting_today` to use
  `telegram_provider.utils.send_message`.
- Remove any standalone `telegram.Bot` instantiation.
- Import `send_message` from `telegram_provider` (the `spotting` ↔
  `telegram_provider` cycle already exists and permits this import).

#### 3. `incident` app (partly done; official-post announcements already use `send_message`)

- Add incident alert sending via the same egress path.
- Use the same `send_message` helper — no direct Telegram API calls.

#### 4. `mlptf` app (future)

- Add badge announcement sending via the same egress path.
- Use the same `send_message` helper.

#### 5. `TelegramLogs` model (done)

- Ensure `OUTBOUND` direction is written for all sends.
- Add `retry_count`, `last_error`, and `sent_at` fields for a complete audit
  trail (see Data Model Changes below).

#### 6. Error handling (mostly done)

- Replace `infinite_retry_on_error` with bounded retry in `telegram_provider`. (Done.)
- Use `TELEGRAM_ADMIN_CHAT_ID` for error notifications. (Done in `error_handler` and
  `send_message`.)
- Route messages that exhaust retries to a dead letter queue. *(Partly: exhausted
  sends keep `sent_at` NULL in `TelegramLogs`; no separate queue exists.)*

### Data Model Changes

```python
# TelegramLogs additions
retry_count = models.PositiveIntegerField(default=0)
last_error = models.TextField(blank=True, default="")
sent_at = models.DateTimeField(null=True, blank=True)
```

Plus a migration for these fields (done: `0004_telegramlogs_last_error_telegramlogs_retry_count_and_more`).
`direction` already supports `OUTBOUND`; no change needed there.

## Acceptance Criteria

- [ ] All outbound Telegram goes through a single `send_message` helper.
- [ ] Every send is logged to `TelegramLogs` with `direction=OUTBOUND`.
- [ ] Bounded retry (max 3) with exponential backoff.
- [ ] Rate limiting enforced (30 msg/sec per chat).
- [ ] Failed messages after max retries go to a dead letter queue.
- [ ] Admin notified via `TELEGRAM_ADMIN_CHAT_ID` on persistent failures.
- [ ] `report_spotting_today` still delivers digests on schedule.
- [ ] No standalone `Bot` instances in any task.

## Dependencies & Blockers

- **`spotting` ↔ `telegram_provider` cycle** already exists and permits the
  import — no new cross-app edge to break.
- **PTB `Application` lifecycle**: `ptb_application` is set during ASGI lifespan
  startup. `get_ptb_application()` builds one lazily when none exists, and raises
  `TelegramBotNotReady` if `TELEGRAM_BOT_TOKEN` is unset.
- **WSGI compatibility**: `views.py` still binds `ptb_application` at import time
  (known issue), so the webhook view is affected. The send helper resolves the
  application lazily, so it does not rely on an import-time binding.
- **Celery worker context**: Celery workers do not serve ASGI, so
  `ptb_application` may be `None` inside a task. Handled by `get_ptb_application()`
  (lazy build, explicit `TelegramBotNotReady`).

## Implementation Phases

1. **Phase 1**: Add `send_message` helper in `telegram_provider` with logging +
   bounded retry (backward compatible — nothing else changes). **Done (2026-08-25).**
2. **Phase 2**: Refactor `spotting.tasks.report_spotting_today` to use the
   helper. **Done.**
3. **Phase 3**: Add dead letter queue + admin notifications via
   `TELEGRAM_ADMIN_CHAT_ID`. **Partly done:** admin notifications yes; no dead-letter queue.
4. **Phase 4**: Add incident alert sending (future). **Partly done:** official-post
   announcements go through `send_message`.
5. **Phase 5**: Add badge announcement sending (future).

## Testing Strategy

- Unit tests for `send_message` with a mock PTB `Application`.
- Integration test for `report_spotting_today` digest delivery.
- Retry logic tests: success on first attempt, success after transient
  failure, permanent failure (exhausts retries → dead letter queue).
- Rate limiting tests (30 msg/sec per chat enforced).
- Dead letter queue tests.
- Audit-trail tests: `TelegramLogs` row written with `direction=OUTBOUND`,
  correct `retry_count`, `last_error`, and `sent_at`.

## Rollout Plan

- Deploy the `send_message` helper first (backward compatible — existing
  behavior unchanged).
- Switch `report_spotting_today` to the helper in the same deploy.
- Monitor: delivery success rate, retry counts, and admin notifications.

## Must Not Do

- Do **not** create new `Bot` instances.
- Do **not** bypass `telegram_provider`'s PTB `Application`.
- Do **not** remove existing `CommandHandler`s.

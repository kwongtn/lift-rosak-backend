# Feature 2: One Governed Egress Path for All Outbound Messaging

## Feature Overview

**Problem**: Outbound Telegram is ungoverned. There is no single owner for
sending messages to users and channels — every caller that wants to talk to
Telegram either reaches around `telegram_provider`'s PTB application or
duplicates its plumbing:

- `spotting.tasks.report_spotting_today` sends digests outside the governed
  path — historically it instantiated its **own** `telegram.Bot` instead of
  reusing the PTB `Application` and its managed `httpx` client.
- `telegram_provider.models.TelegramLogs.direction` has an `OUTBOUND` member
  (`MessageDirection.OUTBOUND = 1`) that is **never written** — the model's own
  comment reads `# TODO: We only record inbound for now`. There is no delivery
  audit trail for anything we send.
- `telegram_provider.handlers.error_handler` only `print`s its error report; the
  developer-DM `send_message` is commented out, so persistent failures are
  silently dropped.
- `settings.TELEGRAM_ADMIN_CHAT_ID` is declared and never consumed anywhere.
- `telegram_provider.utils.infinite_retry_on_error` retries unbounded with 10s
  sleeps — a single stuck message can pin a Celery worker indefinitely (already
  catalogued in `docs/APPS.md` Known Defects & Traps).

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
  disabled), and initialized/started only during ASGI lifespan
  (`ASGILifespanSignalHandler.startup`). The managed `httpx.AsyncClient` is
  created in `startup` and closed in `shutdown` but is currently consumed by
  **no** handler — a prepared seam for outbound HTTP. `handlers_dict` registers
  only `CommandHandler`s (inbound `/`-commands); there is no
  `MessageHandler` or any outbound send path.
- **`telegram_provider.handlers`**: All inbound command handlers
  (`ping`, `help`, `dadjoke`, `verify`, `help_spotting`, `delete`, `spot`,
  `spotting_today`, `favourite_vehicle`) plus `error_handler`, which builds an
  HTML error report and only `print`s it.
- **`telegram_provider.views`**: `TelegramInbound` webhook view — writes
  `TelegramLogs(direction=INBOUND)` then forwards the update to
  `ptb_application.process_update(...)`. It binds `ptb_application` at import
  time (known WSGI caveat, see Dependencies & Blockers).
- **`telegram_provider.models.TelegramLogs`**: `direction` + `payload` only.
  No retry/error/sent-at fields. `OUTBOUND` is never written.
- **`telegram_provider.enums.MessageDirection`**: `INBOUND = 0`, `OUTBOUND = 1`.
- **`telegram_provider.utils`**: `infinite_retry_on_error` (unbounded
  `while True` + `asyncio.sleep(10)`) and `get_daily_updates` (renders the
  digest HTML).
- **`spotting.tasks.report_spotting_today`**: Nightly digest task. Currently
  imports `ptb_application` from `telegram_provider.apps` and calls
  `ptb_application.bot.send_message(...)` directly — bypassing any logging,
  retry, or rate limiting, and reaching around the app's own abstraction. The
  digest is scheduled in `rosak/celery.py`'s `beat_schedule`.
- **`common.tasks`**: General Celery work (NSFW moderation, media conversion,
  verification-code cleanup). Does **not** contain `infinite_retry_on_error` —
  that lives in `telegram_provider.utils`.

> **Note on drift**: `docs/APPS.md` describes `report_spotting_today` as
> instantiating its own `telegram.Bot`. The current source already imports the
> shared `ptb_application`; the remaining work is routing it through the
> governed `send_message` helper so sends are logged, retried, and rate-limited.

## Technical Requirements

### Backend Changes (rosak_backend)

#### 1. `telegram_provider` app

- Add a `send_message(chat_id, text, **kwargs)` helper in
  `telegram_provider/utils.py`.
  - Uses the PTB `Application`'s bot instance and the managed `httpx` client
    (no new `Bot`, no new client).
  - Logs every attempt to `TelegramLogs` with `direction=OUTBOUND`.
  - Implements bounded retry — max 3 attempts, exponential backoff.
  - Respects rate limits (30 messages/second per chat).
- Keep all existing `CommandHandler`s intact.

#### 2. `spotting` app

- Refactor `report_spotting_today` to use
  `telegram_provider.utils.send_message`.
- Remove any standalone `telegram.Bot` instantiation.
- Import `send_message` from `telegram_provider` (the `spotting` ↔
  `telegram_provider` cycle already exists and permits this import).

#### 3. `incident` app (future)

- Add incident alert sending via the same egress path.
- Use the same `send_message` helper — no direct Telegram API calls.

#### 4. `mlptf` app (future)

- Add badge announcement sending via the same egress path.
- Use the same `send_message` helper.

#### 5. `TelegramLogs` model

- Ensure `OUTBOUND` direction is written for all sends.
- Add `retry_count`, `last_error`, and `sent_at` fields for a complete audit
  trail (see Data Model Changes below).

#### 6. Error handling

- Replace `infinite_retry_on_error` with bounded retry in `telegram_provider`.
- Use `TELEGRAM_ADMIN_CHAT_ID` for error notifications (wire the currently
  commented-out `error_handler` send to the setting instead of a hardcoded
  string).
- Route messages that exhaust retries to a dead letter queue.

### Data Model Changes

```python
# TelegramLogs additions
retry_count = models.PositiveIntegerField(default=0)
last_error = models.TextField(blank=True, default="")
sent_at = models.DateTimeField(null=True, blank=True)
```

Plus a migration for these fields. `direction` already supports `OUTBOUND`;
no change needed there.

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
- **PTB `Application` lifecycle**: `ptb_application` is only initialized during
  ASGI lifespan startup. `send_message` must be called from a context where the
  application has been started (or guard against `None` and raise explicitly).
- **WSGI compatibility**: `views.py` binds `ptb_application` at import time
  (known issue). Under WSGI the lifespan signals never fire and the bot stays
  `None`. The send helper must resolve the application lazily rather than
  relying on an import-time binding.
- **Celery worker context**: Celery workers do not serve ASGI, so
  `ptb_application` may be `None` inside a task. `report_spotting_today`
  currently assumes a started bot; the refactor must address this (e.g. lazy
  initialization or an explicit "bot not ready" error path).

## Implementation Phases

1. **Phase 1**: Add `send_message` helper in `telegram_provider` with logging +
   bounded retry (backward compatible — nothing else changes).
2. **Phase 2**: Refactor `spotting.tasks.report_spotting_today` to use the
   helper.
3. **Phase 3**: Add dead letter queue + admin notifications via
   `TELEGRAM_ADMIN_CHAT_ID`.
4. **Phase 4**: Add incident alert sending (future).
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

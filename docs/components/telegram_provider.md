# Component: telegram_provider

## 📌 Purpose & Scope

- **Core Responsibility:** The Telegram bridge. It is the sole ingress/egress adapter between Telegram chats and the domain apps: it accepts Telegram webhook updates, persists every raw payload for audit/replay, dispatches slash-commands to handlers, converts free-form command text into structured spotting submissions (writing `spotting.Event` rows), links Telegram identities to `common.User`, and pushes daily digest messages back to line channels.
- **Domain/Layer:** Django integration / adapter layer — ASGI-async views + `python-telegram-bot` (PTB) `Application`, a thin persistence layer (2 models), and Celery maintenance tasks. It owns no transport domain concepts of its own; it borrows them from `operation` and `spotting`.

## 🔌 Interface & Data Flow

### Entry point: webhook only (no polling)

- `telegram_provider/urls.py` registers a single route, mounted by `rosak/urls.py` at `path("telegram_provider/", include(...))` → so the public webhook endpoint is `POST {TELEGRAM_TLD}/telegram_provider/`.
- `views.TelegramInbound` (DRF `APIView`, `post` wrapped in `async_to_sync`): parses `request.body` as JSON → `TelegramLogs.objects.acreate(payload=body, direction=MessageDirection.INBOUND)` → `ptb_application.process_update(Update.de_json(...))` → returns bare `200 OK`. Note it always answers 200, so Telegram never retries even on handler failure; the raw payload is already durable by then.
- Polling is explicitly **disabled**: the PTB app is built with `.updater(None)` in `apps.py`, i.e. PTB is used purely as a dispatch/HTTP-client library and Django owns the HTTP listener.
- **Caveat:** `views.py` does `from telegram_provider.apps import ptb_application` at import time, binding the module-level `None` value. The name is rebound inside `ASGILifespanSignalHandler.startup`, so the view's captured reference can be stale — a latent import-binding bug worth knowing about (an under-WSGI or pre-lifespan request would `AttributeError` on `None`).

### Bot lifecycle (`apps.py`) — ASGI lifespan, not `ready()` work

`TelegramProviderConfig.ready()` does *no* network I/O. It only connects `django_asgi_lifespan.signals.asgi_startup` / `asgi_shutdown` to an `ASGILifespanSignalHandler` bound to the app config (`weak=False` so the handler survives GC). Actual bot setup happens on the ASGI **lifespan startup** event, which requires `rosak/asgi.py`'s `django_asgi_lifespan.asgi.get_asgi_application()` plus the `django_asgi_lifespan.middleware.LifespanStateMiddleware` entry in `settings.MIDDLEWARE`. Under WSGI, or any server that skips the lifespan protocol, the bot is simply never initialised.

`startup()` sequence:

1. Short-circuits with a warning if `TELEGRAM_BOT_TOKEN` is unset → bot functionality silently disabled (dev-friendly).
2. Builds and `initialize()`/`start()`s the PTB `Application` into the module-global `ptb_application`.
3. **Self-registering webhook:** reads `bot.get_webhook_info()` and, if it differs from `f"{TELEGRAM_TLD}/telegram_provider/"`, calls `set_webhook(url=..., allowed_updates=Update.ALL_TYPES)`. Deployment needs no manual webhook step; `TELEGRAM_TLD` is the single source of truth.
4. Creates a shared `httpx.AsyncClient(timeout=settings.TELEGRAM_HTTPX_TIMEOUT)` and stashes it on the app config (`HTTPXAppConfig` Protocol declares the `httpx_client` attribute). It is currently allocated and closed but not consumed by any handler — a prepared seam for outbound HTTP.
5. Imports handlers lazily (avoids `AppRegistryNotReady`), merges them into `handlers_dict` under the `"handler"` key.
6. **Command-menu reconciliation:** diffs `bot.get_my_commands()` against `handlers_dict` (by key set symmetric difference and by description mismatch) and only calls `set_my_commands()` when drift is detected — so the Telegram-side command menu is declaratively derived from `handlers_dict`.
7. Registers one `CommandHandler` per dict entry plus `add_error_handler(error_handler)`.

`shutdown()` stops the PTB app and closes the httpx client (no-op if the bot never started).

### Handler dispatch table

`handlers_dict` in `apps.py` is the single registry — keys are command names, values carry `description` (Telegram menu text), optional `help_prompt` (usage line shown by `/help`) and optional `help_text` (overrides `description` in `/help`). The `handlers_mapping` in `startup()` binds callables from `handlers.py`:

| Command(s) | Handler | Behaviour |
| --- | --- | --- |
| `/ping` | `ping` | Sets 👍 reaction as a liveness proof (swallows errors). |
| `/help` | `help` | Renders `handlers_dict` into an HTML command list. |
| `/dadjoke` | `dad_joke` | Blocking `requests.get` to icanhazdadjoke.com inside an async handler (blocks the event loop). |
| `/verify [6-digit code]` | `verify` | Validates a `common.UserVerificationCode`, stamps `User.telegram_id`, deletes the code. |
| `/help_spotting` | `help_spotting` | Returns `spotting_parser().format_help()` — help text generated from the argparse spec. |
| `/fav` | `favourite_vehicle` | Aggregates `spotting.Event` counts per vehicle for this user on the channel's line. |
| `/spot`, `/s` | `spot` | The main ingestion path (below). |
| `/delete` | `delete` | Reply-to-message deletion of a spotting entry. |
| `/spotting_today` | `spotting_today` | Renders `utils.get_daily_updates(line_id)` for the channel's line. |
| — | `error_handler` | Formats update + `chat_data`/`user_data` + traceback into an HTML report; **currently only `print`s it** (the developer-DM `send_message` is commented out, and `TELEGRAM_ADMIN_CHAT_ID` is unused).

**Channel→line binding:** most handlers resolve context via `operation.Line.objects.filter(telegram_channel_id=update.effective_chat.id)`. A chat with no bound line cannot spot ("No line assigned for this channel").

### Parsing strategy (`parsers.py`) — argparse, not regex/NLP

This is the closest thing to a text-understanding layer in the repo, and it is deliberately **grammar-based rather than heuristic**: no regexes, no keyword matching, no fuzzy intent detection. `spotting_parser()` builds a real `argparse.ArgumentParser` (`prog="/spot"`, `add_help=False`) and handlers feed it `update.message.text.split(" ")[1:]`, so Telegram message text is treated exactly like a CLI argv vector.

- Subclass `ArgumentParser` overrides `error()` to `raise ArgumentError` instead of `sys.exit()` — mandatory, since argparse's default would kill the worker. `spot` catches `ArgumentError`, replies with the message and reacts 👎.
- Subclass `Formatter(argparse.HelpFormatter)` overrides `_format_action_invocation` and `_format_usage` to wrap tokens in `<code>` tags and to preserve declaration order, so `format_help()` emits Telegram-HTML directly. Help text and the actual grammar can never drift apart.
- Grammar: positional `vehicle_number`; flags `--anon` (store_true), `-w/--wheel-status` (int, choices 1–5), `-s/--status` (int, choices 1–4, default 1), `-r/--run-number` (str), `-n/--notes` (`nargs="+"`, joined with spaces).
- Integer codes are mapped to domain enums in `handlers.spot` via `wheel_status_map` → `SpottingWheelStatus` (FRESH/NEAR_PERFECT/FLAT/WORN_OUT/WORRYING) and `status_map` → `SpottingVehicleStatus` (IN_SERVICE/NOT_IN_SERVICE/DECOMMISSIONED/TESTING).
- A commented-out `-l/--loc/--location` argument (station-code or underscore-separated name ranges, "significant character strategy") plus a `# TODO: Location to determine spotting type` in `spot` mark the intended next expansion.

### `/spot` write path

Verified user lookup by `telegram_id` → argparse → channel's `Line` → `Vehicle` match on `identification_no__istartswith` within those lines, excluding `VehicleStatus.MARRIED`/`DECOMMISSIONED` → builds a `spotting.Event` with `spotting_date` normalised from the Telegram message timestamp through UTC into `settings.TIME_ZONE`, `type=SpottingEventType.JUST_SPOTTING`, `data_source_id` = the `EventSource` named `SpottingDataSource.TELEGRAM` → saves, then joins it to the newest matching `TelegramLogs` row via `TelegramSpottingEventLog`. Success → 👍, any failure → 👎 and re-raise. `/delete` walks the same join backwards (JSONB lookups `telegram_log__payload__message__message_id` / `__chat__id`) and calls `Event.auser_deletion(user_id=...)`, delegating ownership checks to `spotting`.

### DTOs

`dataclasses.WebhookUpdate(user_id: int, payload: str)` is a PTB-style custom-update wrapper. It is currently **unreferenced** — a placeholder for injecting non-Telegram updates into the PTB dispatcher.

### Celery tasks (`tasks.py`)

- `cleanup_telegram_logs` — deletes `TelegramLogs` with `created <= now() - TELEGRAM_CLEANUP_DAYS` (default 30). Scheduled in `rosak/celery.py` beat as `crontab(hour="3", minute="0")`. Because `TelegramSpottingEventLog.telegram_log` is `CASCADE`, log expiry also removes the spotting↔message join rows (the `Event` itself survives; `spotting_event` is `SET_NULL`), so `/delete` only works within the retention window.
- Outbound digest lives in the *other* direction: `spotting.tasks.report_spotting_today` (beat, 03:00) imports `telegram_provider.utils.get_daily_updates` and pushes it with a standalone `telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)` per line channel — outside this app's PTB application and httpx client.

### Settings consumed

`TELEGRAM_BOT_TOKEN` (None → disabled), `TELEGRAM_TLD` (webhook base URL), `TELEGRAM_CLEANUP_DAYS` (30), `TELEGRAM_HTTPX_TIMEOUT` (30), `TELEGRAM_ADMIN_CHAT_ID` (declared, unused), plus `ENVIRONMENT` (via the local `env_url_dict`, whose values duplicate/diverge from real config) and `TIME_ZONE`.

### Dependencies

`python-telegram-bot` (`Application`, `CommandHandler`, `Update`, `ReactionEmoji`, `BadRequest`/`NetworkError`), `django_asgi_lifespan`, `httpx`, `requests`, `asgiref` (`async_to_sync`, `sync_to_async`), DRF, `model_utils.TimeStampedModel`, `django-advanced-filters` + `generic.admin.JsonPrettifyAdminMixin`.

## ⚙️ Internal State & Logic

- **Process-global mutable state:** `apps.ptb_application` (module global) and `apps.handlers_dict` (mutated in place at startup to attach `"handler"` callables). Both are per-worker, non-shared, and only valid after lifespan startup.
- **Persisted state (3 migrations only — a very stable schema):** `0001_initial`, `0002_alter_telegramspottingeventlog_telegram_log`, `0003_telegramlogs_created_telegramlogs_modified`.
  - `TelegramLogs(TimeStampedModel)` — `direction` (`MessageDirection` IntegerChoices: INBOUND=0, OUTBOUND=1) + `payload` JSONField. Comment notes only inbound is recorded today, so OUTBOUND is currently unused.
  - `TelegramSpottingEventLog` — join table: FK `spotting.Event` (`SET_NULL`, related_name `telegram_logs`) + FK `TelegramLogs` (`CASCADE`, related_name also `telegram_logs`).
- **No conversation/session state.** Every command is stateless and re-derives context from the message (chat id → line, `from_user.id` → user). PTB's `chat_data`/`user_data` are only touched in `error_handler` reporting.
- **Resilience:** `utils.infinite_retry_on_error(obj, fn_name, *args)` retries any bot call in an unbounded loop with 10s sleeps, treating `BadRequest("Message to react not found")` as terminal-success. Used for all reaction calls; note it is genuinely unbounded and can pin a task indefinitely.
- **Reporting logic:** `utils.get_daily_updates(line_id, spotting_date)` is sync ORM code (wrapped in `sync_to_async` by callers) that buckets a line's `VehicleLine` roster into "Not Spotted" / "Spotted Today" / "Spotted Today, to review" and renders Telegram HTML. Its `spotting_date` argument is immediately overwritten with `date.today()` inside the function — so `report_spotting_today`'s "yesterday" intent is silently ignored.

### Cross-app coupling

- **Outbound (this app → others):** reads/writes `common.User` (`telegram_id`), deletes `common.UserVerificationCode`; reads `operation.Line`, `Vehicle`, `VehicleLine`, `VehicleStatus`; **creates and soft-deletes `spotting.Event`** and reads `spotting.EventSource` + the `SpottingDataSource`/`SpottingEventType`/`SpottingVehicleStatus`/`SpottingWheelStatus` enums. It does **not** touch the `incident` app at all.
- **Inbound (others → this app):** `operation.Line.telegram_channel_id` is the routing key that makes the binding possible; `spotting/tasks.py` imports `telegram_provider.utils.get_daily_updates`; `spotting/admin.py` imports `TelegramSpottingEventLog` to surface message provenance in the admin. So `spotting` depends on `telegram_provider` as much as the reverse — a genuine two-way cycle.

## 🧩 Extension Points & Hooks

- **`handlers_dict` (apps.py)** is the primary extension seam: add a key + `description`, add the callable to `handlers_mapping`, and registration, `/help` text, and Telegram menu sync all follow automatically.
- **`spotting_parser()`** — new flags extend both grammar and help text in one place; the commented `--location` argument is the pre-designed next step.
- **`ptb_application.add_handlers`** currently only receives `CommandHandler`s. `MessageHandler`, `CallbackQueryHandler`, and inline-query handlers can be added at the same point with zero schema change — and `dataclasses.WebhookUpdate` plus `MessageDirection.OUTBOUND` are pre-built for custom updates and outbound logging respectively.
- **`app_config.httpx_client`** is an already-managed shared async client awaiting a first consumer (e.g. replacing the blocking `requests` call in `dad_joke`).
- **`ASGILifespanSignalHandler`** — additional startup/shutdown work (health registration, warm caches) attaches to the same signals.
- **`error_handler`** has a ready-made HTML report and an unused `TELEGRAM_ADMIN_CHAT_ID`; wiring the commented `send_message` turns it into real alerting.
- **`TelegramLogs.payload`** retains the full JSON update, making reprocessing/backfill and replay-based testing feasible within the retention window.

## 💡 Potential Feature Opportunities

1. **Deterministic station-location capture, typed at the constraint level.** Uncomment the `-l/--loc/--location` argument in `spotting_parser()` and resolve its tokens by plain string lookup against `operation.StationLine.internal_representation` (station codes like `KG05`, already `unique` per line and separately `unique` globally unless `override_internal_representation_constraint` is set) with fallback to `StationLine.display_name` / `Station.display_name` for the underscore-separated name form. A resolved single station fills `Event.origin_station` and flips `type` from `SpottingEventType.JUST_SPOTTING` to `AT_STATION`; a resolved `A-B` range fills `origin_station` + `destination_station` and sets `BETWEEN_STATIONS`. This closes the `# TODO: Location to determine spotting type` in `handlers.spot` and turns every telegram spotting into a geolocatable data point, which is the difference between "set 01 was seen today" and a usable line-level movement record for a community rail platform.
   **Readiness:** `Partially ready` — the grammar slot, the two FK columns, and the enum members all exist; only the resolver is missing. The hard rule to satisfy is the existing `spotting_event_value_relevant` `CheckConstraint` on `spotting.Event`: `BETWEEN_STATIONS` demands both stations non-null **and** `origin_station != destination_station`, `AT_STATION` demands `origin_station` non-null and `destination_station` **null**, and `DEPOT`/`JUST_SPOTTING`/`LOCATION` demand both null — so an ambiguous or half-resolved location must fall back to `JUST_SPOTTING` with both FKs cleared rather than saving a partial. Files: `telegram_provider/parsers.py` (uncomment + finalise the arg), `telegram_provider/handlers.py` (`spot`, add a station resolver alongside `wheel_status_map`/`status_map`). No migration is needed — `origin_station`/`destination_station` already exist on `spotting.Event`.

2. **Tap-to-confirm vehicle disambiguation and delete confirmation.** `spot` matches vehicles with `identification_no__istartswith=args.vehicle_number` and takes `.afirst()`, but `Vehicle.identification_no` is only unique per `(identification_no, vehicle_type)` and `Meta.ordering = ["identification_no"]`, so `/spot 01` on a line holding `01`, `011`, `012` silently attributes the spotting to the alphabetically first set with no signal to the reporter beyond a 👍. Registering a `CallbackQueryHandler` at the same `ptb_application.add_handlers` call site and replying with an `InlineKeyboardMarkup` of the candidate `identification_no`s would let the user tap the right set before the `Event` is written; the same affordance gives `/delete` a confirm button instead of an irreversible reply-and-react. Feedback today is limited to the 👍/👎 reactions from `infinite_retry_on_error`, which cannot express "which one did you mean?".
   **Readiness:** `Partially ready` — PTB supports it with zero schema change, but pending-choice state has nowhere to live: `Application.builder()` in `apps.ASGILifespanSignalHandler.startup` is built with only `.token()` and `.updater(None)` (no `.persistence()`), and `chat_data`/`user_data` are per-worker in-memory dicts, so a callback query may land on a different ASGI process than the one that offered the buttons. Implement by encoding the whole decision in `callback_data` (Telegram caps it at 64 bytes — e.g. `s:<vehicle_id>:<message_id>` / `d:<event_id>`) and re-deriving user and permission on the callback, honouring `Event.auser_deletion`'s reporter-only and 3-day rules. Files: `telegram_provider/apps.py` (handler registration), `telegram_provider/handlers.py`.

3. **Outbound delivery audit trail on one governed egress path.** `MessageDirection.OUTBOUND` exists in `enums.py` but is never written anywhere, so `TelegramLogs` is inbound-only (the `# TODO: We only record inbound for now` on the model says so) and there is no record of what the bot actually sent, to which chat, or whether it succeeded. Routing every send through one small helper that wraps `ptb_application.bot` — the shared `app_config.httpx_client` is already allocated, closed, and consumer-less — and writing a `TelegramLogs(direction=OUTBOUND)` row per send would give per-chat delivery history, let the 03:00 digest prove it fired, and make `error_handler`'s already-built HTML report a normal logged send to the declared-but-unread `settings.TELEGRAM_ADMIN_CHAT_ID` with the 4096-character split handled in exactly one place. The same chokepoint is where `utils.infinite_retry_on_error` — currently a `while True` with 10s `asyncio.sleep`, which can pin a worker forever on a permanently failing chat — becomes a bounded retry with backoff and a dead-letter log row.
   **Readiness:** `Partially ready` — the enum member, the JSONField, and the httpx client are all in place; the blocker is that egress is not centralised. `spotting/tasks.py::_report_spotting_today` constructs its **own** `telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)` outside this app's PTB `Application`, so it bypasses any shared client, rate limiting, or logging; that duplication has to be collapsed first. Files: `telegram_provider/utils.py` (new send helper + bounded retry), `telegram_provider/handlers.py` (all `reply_html`/`reply_text`/`set_reaction` call sites and `error_handler`), `spotting/tasks.py` (drop the standalone `Bot`), `telegram_provider/apps.py` (expose the client/bot to the helper).

4. **Chat-scoped, indexed spotting provenance.** `spot` links the new `Event` to its source message via `TelegramLogs.objects.filter(payload__message__message_id=update.message.message_id).order_by("-id").afirst()` — with **no chat filter**, while `delete` correctly filters on both `telegram_log__payload__message__message_id` *and* `__chat__id`. Telegram `message_id` is only unique per chat, so two line channels can collide and `spot` can attach a `TelegramSpottingEventLog` row pointing at another chat's message; `TelegramSpottingEventLog` also has no unique constraint on either FK, and `TelegramLogs` declares no `Meta` at all, so every one of these JSONB lookups is an unindexed scan that grows with the retention window. Adding the chat-id filter, a `UniqueConstraint` on `("spotting_event", "telegram_log")`, and a GIN or expression index on `payload` makes provenance trustworthy enough to build on — e.g. a `/mine` recap listing a reporter's recent telegram-sourced `Event`s with jump links to the original messages, which is only correct once the join cannot mis-bind.
   **Readiness:** `Ready` — one filter change plus one migration, no new dependencies. Note that the retention CASCADE is a genuine but *separate* consequence: `cleanup_telegram_logs` deletes `TelegramLogs` older than `TELEGRAM_CLEANUP_DAYS` (30) and `TelegramSpottingEventLog.telegram_log` is `CASCADE`, so message provenance vanishes from the `spotting/admin.py` inline after 30 days — but it does not break `/delete`, because `Event.auser_deletion` already refuses after 3 days, well inside the window. Files: `telegram_provider/handlers.py` (`spot`), `telegram_provider/models.py` + a new migration in `telegram_provider/migrations/`.

5. **Clearance-gated commands and self-serve channel binding with a `/status` diagnostic.** Every handler is world-open today, and channel context is resolved solely through `operation.Line.objects.filter(telegram_channel_id=update.effective_chat.id)` — an unbound chat gets a flat "No line assigned for this channel" with no way to see *why* or to fix it, and no way to check whether the caller's `User.telegram_id` link from `/verify` actually took. A privileged `/bind <line_code>` plus a read-only `/status` (line binding present? caller verified? webhook URL matching `f"{TELEGRAM_TLD}/telegram_provider/"`?) would let channel operators onboard a new line channel themselves instead of needing a Django admin session, which matters for a volunteer-run platform adding lines over time.
   **Readiness:** `Not ready` — there is no authorization concept reachable from a Telegram identity. `common.Clearance.name` is choice-constrained to `common.enums.ClearanceType`, which currently contains only `TRUSTED_MEDIA_UPLOADER`, so a new member (e.g. `TELEGRAM_CHANNEL_ADMIN`) plus a data migration and `UserClearance` rows are prerequisites; `handlers_dict` in `apps.py` has no permission key and `startup()` wraps every entry in a bare `CommandHandler(command, elem["handler"])` with no gate, so a decorator or a `"clearance"` key honoured at that registration point must be introduced. `Line.telegram_channel_id` is `unique=True`, so `/bind` must handle the rebinding/collision case explicitly rather than letting an `IntegrityError` reach `error_handler`. Files: `common/enums.py` + a `common/migrations/` entry, `telegram_provider/apps.py` (`handlers_dict`, `handlers_mapping`, the `add_handlers` loop), `telegram_provider/handlers.py` (new `bind`/`status` handlers).

## 💡 Potential AI Feature Opportunities

1. **Natural-language spotting capture.** The argparse grammar is strict and unforgiving — a free-text `MessageHandler` could pass non-command messages (or `ArgumentError` fallbacks) to an LLM extractor that emits the exact `spot` argv vector, then re-validate through `spotting_parser()` so the deterministic grammar remains the sole writer. `TelegramLogs.payload` history is a ready-made labelled training/eval set (messages paired with the `Event` rows they produced via `TelegramSpottingEventLog`).
2. **Location and photo enrichment.** The stubbed `--location` argument and the `# TODO: Location to determine spotting type` are explicit invitations: an extractor could resolve station names/ranges from text, and a vision model could read set numbers or wheel condition off attached photos (already present in the stored payload) to prefill `vehicle_number`/`wheel_status` for user confirmation.
3. **Conversational digests and anomaly narration.** `get_daily_updates` already computes per-line spotted/not-spotted/to-review buckets on a schedule; layering summarisation over the historical series would let the bot answer "which sets have gone quiet this week?" in-channel and turn the 03:00 digest from a raw roster dump into a narrated report with flagged anomalies.

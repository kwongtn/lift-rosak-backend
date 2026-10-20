# Component: telegram_provider

## 📌 Purpose & Scope

- **Core Responsibility:** The Telegram bridge, the sole ingress/egress adapter between Telegram chats and the domain apps. It accepts webhook updates, persists every raw payload (audit/replay), dispatches slash-commands, turns `/spot` text into `spotting.Event` rows, links Telegram identities to `common.User`, stages plain photo/video messages as `common.TemporaryMedia`, exposes admin-only `/approve`, and is the governed egress path other apps send through (`utils.send_message`: audited, bounded retry, dead-letter).
- **Domain/Layer:** Django integration/adapter layer: ASGI-async DRF view plus `python-telegram-bot` (PTB) `Application`, 3 persistence models, one Celery task. It owns no transport domain concepts; it borrows them from `operation` and `spotting`.

## 🔌 Interface & Data Flow

### Entry point: webhook only (no polling)

- `telegram_provider/urls.py` is mounted at `telegram_provider/` in `rosak/urls.py`. The public endpoint is `POST {TELEGRAM_TLD}/telegram_provider/`.
- `views.TelegramInbound` (`post` wrapped in `async_to_sync`) parses the body, writes an INBOUND `TelegramLogs` row, calls `ptb_application.process_update(Update.de_json(...))`, and always returns `200`. Telegram therefore never retries; the raw payload is already durable.
- Polling is off: the PTB app is built with `.updater(None)`. PTB is used as a dispatch and HTTP client; Django owns the listener.
- **Trap:** `views.py` imports `ptb_application` at import time, binding the initial `None`. `startup` rebinds the module global, so the view keeps a stale reference. A request that arrives before lifespan startup, or under WSGI, fails on `None`. `utils.get_ptb_application()` reads the global at call time, so egress is unaffected.

### Bot lifecycle (`apps.py`): ASGI lifespan, not `ready()` work

- `TelegramProviderConfig.ready()` does no network I/O. It returns early with a warning when `TELEGRAM_BOT_TOKEN` or `TELEGRAM_TLD` is unset (feature disabled). Otherwise it connects `asgi_startup` / `asgi_shutdown` to an `ASGILifespanSignalHandler` (`weak=False`, so the handler survives GC).
- Bot setup runs on ASGI lifespan startup. That needs `rosak/asgi.py` built with `django_asgi_lifespan` and `LifespanStateMiddleware` in `MIDDLEWARE`. Under WSGI, or any server that skips the lifespan protocol, the bot never initialises. Celery workers do not run the lifespan; they use `get_ptb_application()` instead.

`startup()` sequence:

1. Build and `initialize()` / `start()` the PTB app into the module global `ptb_application`.
2. Self-register the webhook: if `bot.get_webhook_info().url` differs from `f"{TELEGRAM_TLD}/telegram_provider/"`, call `set_webhook(allowed_updates=Update.ALL_TYPES)`.
3. Create a shared `httpx.AsyncClient(timeout=TELEGRAM_HTTPX_TIMEOUT)` on the app config (`HTTPXAppConfig` protocol). It is allocated and closed but no handler uses it yet.
4. Import handlers lazily (avoids `AppRegistryNotReady`) and bind them into `handlers_dict[...]["handler"]`.
5. Reconcile the command menu: call `set_my_commands()` only when the key set or any description differs from `bot.get_my_commands()`. The menu is derived from `handlers_dict`.
6. Register one `CommandHandler` per entry, the `media` `MessageHandler` (photo, video, animation, document; `& ~filters.COMMAND`), and `error_handler`.

`shutdown()` stops the app and closes the httpx client.

### Handler dispatch table

`handlers_dict` in `apps.py` is the single registry. Each entry has `description` (menu text), optional `help_prompt` (usage line in `/help`), and optional `help_text` (overrides `description` in `/help`). `startup()`'s `handlers_mapping` binds the callables from `handlers.py`.

| Command(s) | Handler | Behaviour |
| --- | --- | --- |
| `/ping` | `ping` | Sets a 👍 reaction as a liveness proof (swallows errors). |
| `/help` | `help` | Renders `handlers_dict` as an HTML command list. |
| `/dadjoke` | `dad_joke` | Blocking `requests.get` to icanhazdadjoke.com inside an async handler (stalls the event loop). |
| `/verify [6-digit code]` | `verify` | Validates a `common.UserVerificationCode`, sets `User.telegram_id`, deletes the code. |
| `/help_spotting` | `help_spotting` | `spotting_parser().format_help()`, generated from the argparse spec. |
| `/fav` | `favourite_vehicle` | Per-vehicle `spotting.Event` counts for this user on the channel's line. |
| `/spot`, `/s` | `spot` | Main ingestion path (see below). |
| `/delete` | `delete` | Reply-to deletion. Finds the Event through `TelegramSpottingEventLog` matching message id and chat id, then calls `Event.auser_deletion(user_id)`. Ownership and 3-day rules live in `spotting`. |
| `/spotting_today [date] [--inis] [--use-actual-date \| --cutoff=HHMM]` | `spotting_today` | Renders `utils.get_daily_updates(...)` for the channel's line. "Today" is `utils.effective_spotting_date(now, cutoff)` in `settings.TIME_ZONE`: the default 03:00 cutoff makes 00:00 to 02:59 count as the previous day. `--use-actual-date` uses midnight; `--cutoff=HHMM` uses a custom time (the two flags are mutually exclusive). An explicit date is never shifted. |
| `/link` | `submit_link` | Submits a social-media link to an incident on this line. Grammar in `parsers.link_parser()` (URL, incident id, title). |
| `/deletelink` | `delete_link` | Deletes a link the caller submitted (reply to it). |
| `/approve` | `approve` | Admin only (`rosak.permissions.has_admin_claim`). Reply to a media message or its review message: a held `AWAITING_REVIEW` `TemporaryMedia` is set to `OVERRIDE_CLEARED` and dispatched for conversion. If no media matches, it falls through to `TelegramSocialMediaLinkLog` and flips a `PENDING_APPROVAL` `SocialMediaLink` to `LIVE`. An already-`LIVE` link gets "Link is not awaiting approval." Official ingestion publishes `LIVE`, so the link branch only fires for legacy or imported pending rows. |
| (plain message) | `media` | Non-command photo, video, animation, or document messages. The sender must have a `/spot` entry on the channel's line; the media attaches to their latest one. Stages a `TemporaryMedia`: `TRUSTED_CLEARED` for `TRUSTED_MEDIA_UPLOADER`, `AWAITING_REVIEW` for untrusted video, `PENDING` otherwise. When `IMAGE_UPLOAD` is off it still records the row, with `metadata.uploads_disabled=True`, so publication is gated later. Not in `handlers_dict`. |
| (error) | `error_handler` | Builds an HTML report (update, chat and user data, traceback). It `print`s the report and, when `TELEGRAM_ADMIN_CHAT_ID` is set, sends it with `send_message`. |

**Channel to line binding:** handlers resolve context with `operation.Line.objects.filter(telegram_channel_id=update.effective_chat.id)`. A chat with no bound line cannot spot ("No line assigned for this channel").

### Parsing strategy (`parsers.py`): argparse, not regex or NLP

- Deliberately grammar-based: no regexes, keyword matching, or fuzzy intent. `spotting_parser()` is a real `argparse.ArgumentParser` (`prog="/spot"`, `add_help=False`). Handlers pass `update.message.text.split(" ")[1:]` as argv.
- The subclass overrides `error()` to `raise argparse.ArgumentError(None, message)` instead of `sys.exit()` (handlers catch `argparse.ArgumentError`; `str(e)` is the bare message). This is mandatory: argparse's default would kill the worker. `spot` replies with the message and reacts 👎.
- The `Formatter` subclass wraps tokens in `<code>` and keeps declaration order, so `format_help()` emits Telegram HTML directly. Help text and grammar cannot drift.
- `/spot` grammar: positional `vehicle_number`; `--anon`; `-w/--wheel-status` (int 1 to 5); `-s/--status` (int 1 to 4, default 1); `-r/--run-number`; `-n/--notes` (`nargs="+"`, joined with spaces).
- Code maps are applied in `handlers.spot`. `wheel_status_map`: 1 FRESH, 2 NEAR_PERFECT, 3 FLAT, 4 WORN_OUT, 5 WORRYING (`SpottingWheelStatus`). `status_map`: 1 IN_SERVICE, 2 NOT_IN_SERVICE, 3 DECOMMISSIONED, 4 TESTING (`SpottingVehicleStatus`).
- The commented-out `-l/--loc/--location` argument and the `# TODO: Location to determine spotting type` in `spot` mark the intended next step.
- `spotting_today_parser()` and `link_parser()` follow the same pattern.

### `/spot` write path

1. Look up the verified user by `telegram_id`. Parse argv.
2. Get the lines bound to the channel, then every `Vehicle` on those lines, excluding `MARRIED` and `DECOMMISSIONED`.
3. Match in Python on the exact, case-insensitive **match key** (`handlers.vehicle_number_match_key`). Spaces are stripped when they are the number's only special characters; otherwise the text before the first space is kept. Examples: `EMU 03` becomes `EMU03`; `03 (40 renum)` becomes `03`. The first match wins, in `Vehicle.Meta.ordering` (`identification_no`). Two vehicles with the same key are ambiguous, and the reporter gets only 👍.
4. Build `spotting.Event`: `spotting_date` is the message timestamp converted UTC to `settings.TIME_ZONE`; `type=JUST_SPOTTING`; `data_source` is the `EventSource` named `TELEGRAM`. Save it, and in parallel fetch the newest `TelegramLogs` row whose `payload.message.message_id` matches. Create the `TelegramSpottingEventLog` join row.
5. Success: 👍. Any failure: 👎, then re-raise.

**Trap:** step 4's provenance lookup has no chat filter (`/delete` has one). Telegram message ids are unique only per chat, so a collision can bind the Event to another chat's message.

### DTOs

`dataclasses.WebhookUpdate(user_id, payload)` is unreferenced. It is a placeholder for injecting non-Telegram updates into the PTB dispatcher.

### Celery tasks (`tasks.py`)

- `cleanup_telegram_logs` deletes `TelegramLogs` older than `TELEGRAM_CLEANUP_DAYS`. Beat: `crontab(hour="3", minute="0")` in `rosak/celery.py`. Both join tables CASCADE from `TelegramLogs`, so expiry removes the Event-to-message join rows. The `Event` survives (`spotting_event` is SET_NULL). `/delete` therefore only works within retention, and `auser_deletion` refuses after 3 days in any case.
- The 00:00 daily digest is owned by `spotting`: `spotting.tasks.report_spotting_today` calls `utils.get_daily_updates` and sends through `utils.send_message`, once per distinct line channel. See the spotting doc.

### Settings consumed

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_TLD`, `TELEGRAM_ADMIN_CHAT_ID` (`rosak/settings.py` ~L506-508). The admin chat is used by `error_handler`, by `send_message`'s dead-letter ping, and by `incident.tasks` official-post notifications. A blank value disables all three.
- `TELEGRAM_CLEANUP_DAYS` (default 30) and `TELEGRAM_HTTPX_TIMEOUT` (default 30), `settings.py` ~L509-510. Parsed with `int(...)` / `float(...)`, so an env override is a number; the consuming code (`cleanup_telegram_logs`, `apps.py`) does no coercion of its own.
- `ENVIRONMENT` (via `env_url_dict` in `handlers.py`, whose hostnames duplicate config) and `TIME_ZONE`.

### Dependencies

`python-telegram-bot` (`Application`, `CommandHandler`, `MessageHandler`, `Update`, `ReactionEmoji`, `BadRequest`, `NetworkError`, `RetryAfter`), `django_asgi_lifespan`, `httpx`, `requests`, `asgiref`, DRF, `model_utils.TimeStampedModel`. Admin uses `advanced_filters` and `generic.admin.JsonPrettifyAdminMixin`. Cross-app imports: `common` (User, UserVerificationCode, TemporaryMedia, ClearanceType), `operation` (Line, Vehicle, VehicleLine, VehicleStatus), `spotting` (Event and enums), `incident` (`SocialMediaLink` for `/approve` and `/deletelink`).

## ⚙️ Internal State & Logic

- **Process-global mutable state:** `apps.ptb_application` (set at lifespan startup), `apps.handlers_dict` (mutated at startup to attach `"handler"`), and `utils.rate_limiter`. All are per worker process and not shared.
- **Persisted state (migrations 0001 to 0005):**
  - `TelegramLogs(TimeStampedModel)`: `direction` (`MessageDirection`: INBOUND=0, OUTBOUND=1), `payload` JSON, `retry_count`, `last_error`, `sent_at` (for OUTBOUND rows, NULL means dead-letter). It has no `Meta`, so `payload` has no index and JSONB lookups scan.
  - Inbound rows hold the whole update, so `payload["message"]` is present. Outbound rows hold the request. With `send_message(..., return_log=True)` they also get `payload["message"]` (`message_id` and `chat.id`), so a reply lookup treats them the same way. The default path leaves the payload untouched.
  - `TelegramSpottingEventLog`: `spotting_event` (FK, SET_NULL, related_name `telegram_logs`) and `telegram_log` (FK, CASCADE, related_name `telegram_logs`). Neither FK is unique.
  - `TelegramSocialMediaLinkLog`: `social_media_link` (`incident.SocialMediaLink`, CASCADE) and `telegram_log` (CASCADE). Written by `incident.tasks` after each official-post notification. It is the only bridge from this app into `incident`, and it is what makes the notification approvable by reply.
- **No conversation state.** Every command re-derives its context from the message: chat id to line, `from_user.id` to user. `chat_data` and `user_data` are read only in `error_handler`.
- **Retries and egress (`utils.py`):**
  - `retry_on_error(obj, fn_name, ...)`: bounded (default 3 attempts, backoff `base ** attempt`). Used for reactions. `BadRequest("Message to react not found")` counts as success.
  - `send_message(chat_id, text, *, return_log=False, **kwargs)`: the single chokepoint for bot sends. It writes the OUTBOUND row before the first attempt, then applies a per-chat sliding-window limiter (`PerChatRateLimiter`, 30 sends per second). It makes up to `MAX_RETRIES=3` attempts with `2 ** attempt` second backoff, honouring PTB `RetryAfter`. Success sets `sent_at`. Final failure leaves `sent_at=None`, sends a best-effort direct ping to the admin chat (no recursion), and returns `None`.
  - `return_log=True` (keyword-only) returns `(message, log)` and stamps the outbound payload. Use it when a human will act on the message by replying. The default returns the bare `Message`, so existing callers are unchanged.
  - `get_ptb_application()`: returns the lifespan-started app, or lazily builds one (`initialize()` and `start()`, no webhook) so Celery workers can send. Raises `TelegramBotNotReady` when no token is set. It uses a function-local import so it reads the current global.
- **Digest logic:** `utils.get_daily_updates(line_id, spotting_date=None, include_not_in_service=False)` is sync ORM code; callers wrap it. The spotted set is `Event.spotting_date == (spotting_date or today)`. The line's `VehicleLine` roster is bucketed into "Not Spotted", "Spotted Today" (status `IN_SERVICE`), and "Spotted Today, to review" (any other status). `MARRIED` and `DECOMMISSIONED` are always excluded; `OUT_OF_SERVICE` is excluded unless `include_not_in_service`.
  - **Trap:** the header is always `date.today()`, whatever the argument. The 00:00 digest, which asks for yesterday's date, is therefore labelled with today's date.
- **Known defects:**
  - `dad_joke` blocks the event loop. `app_config.httpx_client` is the managed client to replace it with.
  - The `views.py` import-time binding (see Entry point).
  - Env-provided numeric settings are strings (see Settings).
  - Provenance lookup in `spot` has no chat filter (see write path).
  - The digest header ignores its date argument (see above).

## 🧩 Extension Points & Hooks

- **`handlers_dict` (`apps.py`)** is the main seam. Add a key with `description`, and add the callable to `handlers_mapping`. Registration, `/help` text, and Telegram menu sync follow automatically.
- **`spotting_parser()`**: new flags extend grammar and help together. The commented `--location` is the pre-designed next step.
- **`ptb_application.add_handlers`** receives `CommandHandler`s from `handlers_dict` plus the `media` `MessageHandler`. `CallbackQueryHandler` and inline-query handlers can be added at the same point with no schema change. `WebhookUpdate` is ready for custom updates.
- **`app_config.httpx_client`**: a managed shared async client waiting for its first consumer.
- **`ASGILifespanSignalHandler`**: extra startup or shutdown work (health registration, cache warm-up) attaches to the same signals.
- **`send_message(..., return_log=True)`**: the path for any announce-and-reply feature. Reply resolution works through `payload["message"]`.
- **`TelegramLogs.payload`** keeps the full JSON update, which makes replay and backfill possible within the retention window.

## 💡 Potential Feature Opportunities

1. **Deterministic station-location capture, typed at the constraint level.** Uncomment `-l/--loc/--location` in `spotting_parser()`. Resolve tokens by string lookup against `operation.StationLine.internal_representation` (station codes such as `KG05`, unique per line and globally unless `override_internal_representation_constraint` is set), then fall back to `StationLine.display_name` / `Station.display_name` for underscore-separated names. One resolved station sets `Event.origin_station` and `type=AT_STATION`. A resolved `A-B` range sets both stations and `type=BETWEEN_STATIONS`. This closes the `# TODO` in `handlers.spot`.
   **Readiness:** `Partially ready`. The grammar slot, both FK columns, and the enum members exist; only the resolver is missing. The `spotting_event_value_relevant` constraint is the hard rule (see the spotting doc). An ambiguous or half-resolved input must fall back to `JUST_SPOTTING` with both FKs null, never a partial save. Files: `parsers.py`, `handlers.py` (resolver next to `wheel_status_map` and `status_map`). No migration.

2. **Tap-to-confirm vehicle disambiguation and delete confirmation.** Ambiguity remains when keys collide: `01` alongside `01 (renum)`, or one `identification_no` on two `vehicle_type`s (the composite `UniqueConstraint` allows that). The first row wins silently. A `CallbackQueryHandler` at the same `add_handlers` call site, replying with an `InlineKeyboardMarkup` of candidates, would let the user pick before the Event is written. The same affordance gives `/delete` a confirm step. Feedback today is only 👍 and 👎, which cannot ask "which one did you mean?".
   **Readiness:** `Partially ready`. PTB needs no schema change, but pending-choice state has nowhere to live: the builder has no `.persistence()`, `chat_data` and `user_data` are per process, and a callback can reach another ASGI worker. Encode the whole decision in `callback_data` (64-byte limit, for example `s:<vehicle_id>:<message_id>` or `d:<event_id>`). Re-derive the user and permissions on callback, honouring `Event.auser_deletion`'s reporter-only and 3-day rules. Files: `apps.py`, `handlers.py`.

3. **Chat-scoped, indexed spotting provenance.** Add the `payload__message__chat__id` filter to the lookup in `spot`. Add `UniqueConstraint(spotting_event, telegram_log)` to `TelegramSpottingEventLog`. Add a `Meta` and a GIN or expression index on `TelegramLogs.payload`. Together these make provenance trustworthy enough to build on, for example a `/mine` recap with jump links to source messages.
   **Readiness:** `Ready`. One filter change and one migration, no new dependencies. Retention interaction: `cleanup_telegram_logs` CASCADEs provenance away after 30 days. `/delete` is not affected, because `auser_deletion` refuses after 3 days. Files: `handlers.py`, `models.py`, new migration.

4. **Clearance-gated commands, self-serve channel binding, and `/status`.** Every handler is world-open. An unbound chat gets a flat "No line assigned" with no way to fix it. A privileged `/bind <line_code>` plus a read-only `/status` (binding present? caller verified? webhook URL matches `{TELEGRAM_TLD}/telegram_provider/`?) would let channel operators onboard a line without a Django admin login.
   **Readiness:** `Not ready`. No authorization is reachable from a Telegram identity. `common.enums.ClearanceType` has only `TRUSTED_MEDIA_UPLOADER`, so a new member (for example `TELEGRAM_CHANNEL_ADMIN`) and a data migration come first. `handlers_dict` has no permission key, and `startup()` wraps every entry in a bare `CommandHandler`, so a `"clearance"` key enforced at that point is needed. `Line.telegram_channel_id` is `unique=True`, so `/bind` must handle rebinding explicitly instead of letting an `IntegrityError` reach `error_handler`. Files: `common/enums.py` plus a `common` migration, `apps.py`, `handlers.py`.

## 💡 Potential AI Feature Opportunities

1. **Natural-language spotting capture.** Route non-command text to an LLM that emits the exact `/spot` argv vector, then re-validate it through `spotting_parser()` so argparse stays the only writer. `TelegramLogs.payload` paired with `TelegramSpottingEventLog` is already a labelled corpus of message to resulting Event.
2. **Location and photo enrichment.** An extractor can resolve station names and ranges from text (feature 1). A vision model can read set numbers or wheel condition from the photos already stored in `payload` and prefill `vehicle_number` and `wheel_status` for the reporter to confirm.
3. **Conversational digests and anomaly narration.** `get_daily_updates` already computes per-line buckets on a schedule. Summarising the history could answer "which sets have gone quiet this week?" in channel, and turn the digest into a narrated report with flagged anomalies.

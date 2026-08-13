# Component: spotting

## 📌 Purpose & Scope

- **Core Responsibility:** Owns the community "vehicle sighting" ledger. A logged-in user records that a specific `operation.Vehicle` was seen on a given date, in a given operational state (in service / testing / decommissioned…), at a place expressed either as station(s), a depot, or raw GPS coordinates — optionally with photos and free-text notes. Everything downstream (fleet status charts, vehicle "last spotted" data, daily Telegram digests) is derived from this ledger.
- **Domain/Layer:** Django business-logic + persistence app, exposed through Strawberry GraphQL (`rosak.schema.Query` / `Mutation` at `POST /graphql/`), Django admin, and Celery. No templates or REST views of its own — media ingestion is delegated to `common`'s `POST /upload/`.

## 🔌 Interface & Data Flow

### Inputs

**GraphQL queries** (`SpottingScalars`, mixed into root `Query`):

| Field | Notes |
| --- | --- |
| `events` | `strawberry_django.field(filters=EventFilter, order=EventOrder, pagination=True)` — the main listing |
| `eventsCount` | resolver `spotting.schema.resolvers.get_events_count` — unfiltered `Event.objects.acount()` |

**`EventFilter`** (`spotting/schema/filters.py`) — declarative lookups on `id`, `type`, `created` (datetime lookups), `spotted` (date lookups), `notes`, `status`, `is_anonymous`, plus a nested `operation.VehicleFilter`. Four custom filter fields carry real logic:
- `has_notes` → `~Q(notes="")`
- `different_status_than_vehicle` → `~Q(vehicle__status=F("status"))`; surfaces sightings that contradict the vehicle's recorded status (moderation queue)
- `is_read` → subquery against `EventRead` for the *requesting* user; returns `queryset.none()` for anonymous callers
- `only_mine` → `Q(reporter_id=info.context.user.id)`
- `free_search` → icontains across `notes`, both station `display_name`s, `vehicle.identification_no`, `vehicle.nickname`

**`EventOrder`**: `id`, `spotting_date`, `created`.

**Mutations** (`SpottingMutations`):

| Mutation | Input | Permissions |
| --- | --- | --- |
| `addEvent` | `EventInput` (partial of `Event`) → `EventScalar` | `IsLoggedIn` (recaptcha check currently commented out) |
| `deleteEvent` | `DeleteEventInput { id }` → `GenericMutationReturn` | `IsLoggedIn`, `IsRecaptchaChallengePassed` |
| `markAsRead` | `MarkEventAsReadInput { event_ids: [ID] }` → `GenericMutationReturn` | `IsLoggedIn`, `IsRecaptchaChallengePassed`, `IsAdmin` |

`EventInput` fields: `spotting_date`, `vehicle: ID`, `notes?`, `run_number?`, `status`, `type`, `wheel_status?`, `origin_station?: ID`, `destination_station?: ID`, `location?: generic.WebLocationInput`, `is_anonymous?`. Note the station IDs are **`operation.StationLine` IDs**, which `add_event` translates to `Station` IDs — and only for `BETWEEN_STATIONS` / `AT_STATION` types.

**Image upload** is *not* a spotting endpoint. Client calls `POST /upload/` (`common.views.GenericUpload`) with `upload_type=SPOTTING_EVENT`, `related_id=<event id>`, `image`. The view verifies `user.id == event.reporter_id`, then creates a `common.TemporaryMedia` row with `metadata.spotting_event_id`.

**Django signals consumed:** none in this app. `Event`/`EventMedia` are written *by* `common.signals.convert_temporary_media_to_media` (`post_save` on `TemporaryMedia`).

### Outputs

- **`EventScalar`** (`@strawberry_django.type(models.Event)`) — flat fields `id`, `created`, `spotting_date`, `notes`, `status`, `type`, `wheel_status`, `run_number`; relations `vehicle: operation.Vehicle`, `origin_station` / `destination_station: operation.Station`; DataLoader-backed fields `reporter: common.UserScalar` (returns `None` when `is_anonymous`), `is_read` (`IsLoggedIn`-gated), `location: LocationEvent`, `media_count: Int`, `medias: [common.MediaScalar]`, and `is_mine`.
- **`LocationEvent`** type — `location` (PointField scalar), `accuracy`, `altitude`, `altitude_accuracy`, `heading`, `speed`.
- **Celery task emitted:** `spotting.tasks.report_spotting_today` (see below).
- **Outbound side effect:** Telegram HTML messages to per-`Line` channels.
- **Reverse consumers of this app's data** (spotting is read *from* elsewhere): `operation.schema.loaders` (`last_spotting_date_from_vehicle_loader`, `spotting_count_from_vehicle_loader`, `spottings_from_vehicle_loader`), `operation.schema.scalars` (`spottingTrends`, `vehicleSpottingTrends`), `common.schema.loaders.spottings_from_user_loader`, `common.schema.scalars.UserScalar.spottings*`, `telegram_provider.models.TelegramSpottingEventLog.spotting_event`, `telegram_provider.handlers` (creates `Event`s from bot commands), `telegram_provider.utils.get_daily_updates`, and `chartography` fleet-status aggregations.

### Dependencies

- **Cross-app FKs out of `spotting`:** `Event.reporter → common.User` (CASCADE), `Event.vehicle → operation.Vehicle` (CASCADE), `Event.origin_station` / `destination_station → operation.Station` (PROTECT), `Event.medias → common.Media` M2M through `EventMedia`, `EventRead.reader → common.User`. `LocationEvent` extends `generic.models.WebLocationModel`.
- **Cross-app FKs into `spotting`:** `telegram_provider.TelegramSpottingEventLog.spotting_event → spotting.Event`.
- **Python/infra:** `strawberry` / `strawberry-django`, `django.contrib.gis` (PostGIS `PointField`), `django_choices_field.TextChoicesField`, `model_utils.TimeStampedModel`, `django.contrib.postgres.indexes.BTreeIndex`, `python-telegram-bot`, `celery`, `firebase_admin` (initialised in `SpottingConfig.ready()` — the app config is the global Firebase bootstrap), `django-advanced-filters` / `django-rangefilter` / `ordered-model` in admin.

## ⚙️ Internal State & Logic

**Models** (`spotting/models.py`):
- `Event` — the aggregate root. `TimeStampedModel`, so `created` is the audit timestamp while `spotting_date` is the user-asserted sighting date; the two are deliberately distinct.
- `LocationEvent` — 1-per-event GPS payload (FK, not OneToOne; loaders assume one and keep the last). `location` is overridden to be non-null.
- `EventRead` — per-user read receipt, `UniqueConstraint(reader_id, event_id)`; written only via `markAsRead` with `ignore_conflicts=True`.
- `EventMedia` — explicit M2M through-table to `common.Media`.
- `EventSource` — lookup table of ingestion channels, named after `SpottingDataSource` values (`SITE`, `TELEGRAM`); `Event.data_source` is `SET_NULL`.

**Enums** (`spotting/enums.py`): `SpottingEventType` (`DEPOT`, `LOCATION`, `BETWEEN_STATIONS`, `JUST_SPOTTING`, `AT_STATION`), `SpottingVehicleStatus` (`IN_SERVICE`, `NOT_IN_SERVICE`, `DECOMMISSIONED`, `TESTING`, `NOT_SPOTTED`, `MARRIED`, `UNKNOWN`), `SpottingWheelStatus` (`FRESH`, `NEAR_PERFECT`, `FLAT`, `WORN_OUT`, `WORRYING`), `SpottingDataSource` (`SITE`, `TELEGRAM`).

**Type/station invariant is enforced in the database**, not just in Python — a `CheckConstraint` named `spotting_event_value_relevant` requires: `BETWEEN_STATIONS` ⇒ both stations set and distinct; `AT_STATION` ⇒ origin only; `DEPOT`/`JUST_SPOTTING`/`LOCATION` ⇒ neither station set. Read paths are optimised by two `BTreeIndex`es: `(vehicle, -spotting_date)` and `(vehicle, run_number, -spotting_date)`.

**Deletion policy** is duplicated in two places: `Event.auser_deletion()` (raises unless caller is the reporter and the event is < 3 days old) and the `deleteEvent` mutation, which re-expresses the same rule as a queryset filter (`reporter_id=user, created__gte=now()-3d`) and returns `ok=False` instead of raising. `auser_deletion` appears to be currently unused by the GraphQL path.

**N+1 avoidance** — `SpottingContextLoaders` (`spotting/schema/loaders.py`) is registered in `rosak.context.ContextLoaders` under key `"spotting"` and deep-copied per request: `reporter_from_event_loader` (filters `is_anonymous=False`, so anonymity is enforced at the loader), `is_read_from_event_loader` (composite `(event_id, reader_id)` key), `location_event_from_event_loader`, `media_count_from_event_loader`, `media_from_event_loader`.

**Image moderation pipeline** (owned by `common`, driven by spotting uploads): `GenericUpload` → `TemporaryMedia(PENDING)` → `post_save` signal → **`convert_temporary_media_to_media_task`**. `common.tasks.check_temporary_media_nsfw` calls a RapidAPI NSFW classifier (`RAPID_API_NSFW_TEST_URL`, threshold `RAPID_API_NSFW_THRESHOLD = 0.5`) and marks the row `BLOCKED` or `CLEARED`, with users holding the `TRUSTED_MEDIA_UPLOADER` clearance short-circuited to `TRUSTED_CLEARED`. ⚠️ **The NSFW step is currently disabled** — both the import and the `apply_async` in `common/signals.py` are commented out, so uploads go straight to conversion. Conversion posts the image to a Discord webhook (Discord is the CDN), creates `common.Media` from the attachment metadata, re-checks `uploader_id == event.reporter_id`, then creates `EventMedia`. `cleanup_temporary_media_task` (every minute) retries stuck `PENDING` rows (`fail_count < 5`) and processes `OVERRIDE_CLEARED` (the manual admin override lever).

**Celery tasks** (`spotting/tasks.py`) — one task: `report_spotting_today`, scheduled in `rosak/celery.py` `beat_schedule` as `crontab(hour="3", minute="0")` (daily 03:00 server time). It is a sync `bind=True` task that deliberately wraps an async body with `asyncio.run(_report_spotting_today())` (comment notes Celery will not await a coroutine task). Body: compute `yesterday = date.today() - 1d`, open a `telegram.Bot(settings.TELEGRAM_BOT_TOKEN)`, iterate `operation.Line` objects with a non-null `telegram_channel_id`, de-duplicating channels so lines sharing a channel get one message, and send `telegram_provider.utils.get_daily_updates(line_id, spotting_date)` as HTML with previews disabled. Caveat: `get_daily_updates` overwrites its `spotting_date` argument with `date.today()` on its first line, so the digest actually reports *today's* sightings despite the task passing yesterday. The digest buckets each line's vehicles into "Not Spotted" / "Spotted Today" / "Spotted Today, to review" (the last being spotted vehicles whose `operation` status is not `IN_SERVICE`), excluding `MARRIED` and `DECOMMISSIONED` stock.

**Schema evolution** (17 migrations, `spotting/migrations/`): initial model (0001) → anonymity + status rework (0003–0005) → BTree index on `(vehicle, spotting_date)` (0006) → read receipts (0007) → GPS `LocationEvent` and altitude (0008–0009) → repeated tightening of the `value_relevant` check constraint (0004, 0010) → `run_number` (0011) → **`0012_modify_spotting_types`** (data migration reshaping the event-type vocabulary) → `EventMedia` M2M (0013) → `wheel_status` (0015) → `EventSource` + `Event.data_source` + source `data` (0016–0017). `0002_fix_incorrect_spotting_key` and `0012` are both flagged as locally modified in git.

**Admin** (`spotting/admin.py`): `EventAdmin` with advanced-filter fields, date-range filters on `spotting_date` / `created`, `list_editable = [run_number, notes]` for triage, a read-only `images_widget()` rendering media thumbnails linked to `/admin/common/media/<id>/change`, and a `TelegramSpottingEventLog` inline. `LocationEventAdmin` uses `generic.views.GeometricForm` for map editing. `EventRead`, `EventMedia`, and `EventSource` are **not** registered.

## 🧩 Extension Points & Hooks

- **`@strawberry_django.filter_field` on `EventFilter`** — the established way to add server-side query semantics (context-aware filters receive `info` and may return `(queryset, Q)`); new filters need no schema-wide changes.
- **`SpottingContextLoaders` dict** — dropping a new `DataLoader` key here and a matching `@strawberry.field` on `EventScalar` adds a batched relation without touching `rosak/context.py`.
- **`EventSource` table + `SpottingDataSource`** — the designed seam for new ingestion channels (a Discord bot, an OCR importer, an open API) without schema migrations; the `EventSource.data` JSON column (migration 0017) is the per-source payload escape hatch.
- **`TemporaryMediaType` + `TemporaryMedia.metadata`** — the moderation pipeline is generic over upload types, so new spotting attachment kinds (video, audio, ticket scans) plug in as new `upload_type` branches.
- **`SpottingConfig.ready()`** — currently only bootstraps Firebase; the natural place to register `post_save` signals on `Event` (there are none today, so e.g. push notification or leaderboard fan-out would attach here).
- **`common.ClearanceType`** — permission gradations (`TRUSTED_MEDIA_UPLOADER`) already exist; new spotting-specific clearances can gate mutations via new `rosak.permissions` classes.
- **Celery beat** — `report_spotting_today` is the template for further scheduled digests; add entries to `app.conf.beat_schedule`.

## 💡 Potential Feature Opportunities

1. **Per-user read/unread inbox for sightings.** Everything needed for "mark this sighting as seen" is already built: the `EventRead` model with its `spotting_eventread_reader_event_unique` constraint, the batched `is_read_from_event_loader`, the `EventScalar.is_read` field (gated only `IsLoggedIn`), and `EventFilter.is_read`, which subqueries `EventRead` for the requesting user. But `markAsRead` carries `IsAdmin` alongside `IsLoggedIn`, so an ordinary user can *read* and *filter on* their own read state yet can never write it — a complete feature switched off for everybody except admins. Un-gating it turns the existing "unread sightings" filter into a real notification inbox, which matters because the daily Telegram digest is currently the only way a user learns that something was spotted.
   **Readiness:** `Ready` — delete `IsAdmin` from the `mark_as_read` permission list at `spotting/schema/schema.py:180`. The mutation body already uses `info.context.user.id` as `reader_id` and `abulk_create(..., ignore_conflicts=True)`, so it is safe for non-admins unchanged; a companion `mark_as_unread` (delete the matching `EventRead` rows) is ~10 lines in the same class and needs no migration.

2. **An `editEvent` mutation, with the contribution window expressed once.** Today the only correction path is destructive — a user who typos a `run_number`, picks the wrong `status`, or mis-taps `wheel_status` must `deleteEvent` and re-file, losing the original `created` timestamp and any attached media. The 3-day rule is also written twice and inconsistently: `Event.auser_deletion()` (`spotting/models.py:135-140`) raises `Exception` and is used *only* by the Telegram `/delete` handler (`telegram_provider/handlers.py:192`), while the `deleteEvent` mutation re-expresses it as `created__gte=now() - timedelta(days=3)` and returns `ok=False`. For a community ledger, in-place correction is the difference between fixing the record and losing the sighting.
   **Readiness:** `Partially ready` — `TimeStampedModel` already supplies `Event.modified` for an audit trail (not exposed on `EventScalar`; commented out of `EventAdmin.list_filter`). Blockers: no `EditEventInput` / `edit_event` exists; editing `type` or the station pair must re-satisfy the `spotting_event_value_relevant` `CheckConstraint`, so the mutation has to repeat the `StationLine → Station` translation `add_event` performs; and the window rule should be hoisted into a single model method (e.g. `Event.is_within_edit_window`) consumed by both the mutation and `auser_deletion`. Files: `spotting/models.py`, `spotting/schema/inputs.py`, `spotting/schema/schema.py`, `spotting/schema/scalars.py`.

3. **A real moderation queue for sightings that contradict the fleet record.** `EventFilter.different_status_than_vehicle` already computes `~Q(vehicle__status=F("status"))` — exactly the "this report disagrees with `operation.Vehicle.status`" predicate a reviewer wants — and `EventAdmin` already has `list_editable = ["run_number", "notes"]` plus advanced filters for triage. What is missing is an *outcome*: nothing records that an item was checked and dismissed, so the same rows resurface forever and two staff members duplicate work. A resolution state turns an ad-hoc filter into a workflow, and is the natural consumer of the digest's existing "Spotted Today, to review" bucket in `telegram_provider.utils.get_daily_updates`.
   **Readiness:** `Partially ready` — the filter is live, but ungated (any caller, including anonymous, may use it). Blockers: no field or model stores a shared verdict (`EventRead` is per-user read state, not a review outcome), so add `Event.review_state` plus `reviewed_by` / `reviewed_at` with a migration, a `review_state` lookup on `EventFilter`, a staff-gated mutation, and an admin action; note also that `spotting/admin.py` does not register `EventRead`, `EventMedia` or `EventSource`, so staff cannot inspect any of them today.

4. **Contributor leaderboards, streaks, and "sets you have never spotted".** The aggregation groundwork exists but has no ranking surface: `common.schema.scalars.UserScalar` already resolves `favourite_vehicles`, `with_most_entries`, `spottings_count` and `spotting_trends` (plain `Count` / `values` queries over `Event`), and `operation.schema.scalars.Vehicle` exposes `last_spotting_date` and `spottingCount`, both backed by `BTreeIndex(["vehicle", "-spotting_date"])`. Consecutive-day streaks are deterministic date arithmetic over `spotting_date` with no new model, and a per-user "gaps in your collection" list is an anti-join between a `Line`'s vehicles and that user's `Event` rows. For a hobbyist rail community this is the primary retention loop, and it needs no new data.
   **Readiness:** `Partially ready` — needs new cross-user resolvers (`spotting/schema/resolvers.py` holds only `get_events_count`), since per-user fields on `UserScalar` cannot rank users against each other. Blockers: `SpottingScalars.events_count` ignores `EventFilter` entirely (bare `Event.objects.acount()`), so no ranked or filtered list can show a total — the commented-out `ListConnectionWithTotalCount` relay connection at `spotting/schema/schema.py:33-38` is the intended fix; `UserScalar.with_most_entries` indexes `[0]` into its aggregate queryset and raises `IndexError` for a user with zero events, which must be fixed before it appears on a public profile; and `VehicleFilter` (`operation/schema/filters.py`) exposes only `id` and `status`, so "never spotted by me" requires a new context-aware `@strawberry_django.filter_field` there.

5. **Map view of sightings, and GPS on every event type.** `LocationEvent` already persists a non-null PostGIS `PointField` plus `accuracy`, `altitude`, `altitude_accuracy`, `heading` and `speed`, and `operation.schema.filters.StationFilter.location` already demonstrates the precise pattern a spotting geo-search would copy — `Q(location__distance_lt=(Point(x, y, z), Distance(km=radius)))`. A "sightings near me / within this viewport" query and a rider-facing map of where stock actually gets seen is the most visible thing this dataset could become, and it would finally make the `LOCATION` and `JUST_SPOTTING` event types meaningful instead of location-less rows.
   **Readiness:** `Not ready` — three concrete blockers. (a) `LocationEvent.event` is a plain `ForeignKey` (`spotting/models.py:16`), so one `Event` may carry many location rows while `batch_load_location_event_from_event` silently keeps whichever arrives last (`spotting/schema/loaders.py:36-39`); de-duplicate existing rows, then migrate to `OneToOneField`. (b) Nothing guarantees a `LOCATION`-typed `Event` actually has coordinates — the `spotting_event_value_relevant` `CheckConstraint` governs only the station columns, and `add_event` creates the `LocationEvent` only `if input.location != strawberry.UNSET`, so the type is decorative; extend the constraint or validate in the mutation. (c) The Telegram ingestion path captures no coordinates at all: `telegram_provider/handlers.py:296` still reads `# TODO: Location to determine spotting type`. Only then add a `location` filter field (radius or bbox) to `EventFilter` in `spotting/schema/filters.py`; distance ordering would also need a new entry in `spotting/schema/orderings.py`.

## 💡 Potential AI Feature Opportunities

1. **Anomaly / plausibility scoring on submission.** The DB already stores `vehicle`, `spotting_date`, `run_number`, `wheel_status`, GPS point, and station pair, and `EventFilter.different_status_than_vehicle` already encodes the "this sighting contradicts the fleet record" concept. A model over the historical `(vehicle, -spotting_date)` index could flag physically impossible sightings (same vehicle at two distant stations minutes apart), wrong-line reports, or copy-paste `run_number`s, writing a confidence score into a new field and feeding the existing admin triage queue.
2. **Vision-assisted auto-fill and richer moderation.** Photos already pass through a Celery task that opens the image with PIL and extracts EXIF. That is the natural insertion point for an image model that OCRs the vehicle `identification_no` / run number to pre-fill `EventInput`, classifies `wheel_status` from bogie shots, and replaces the currently-disabled binary NSFW classifier with a multi-label safety check plus a human-readable rejection reason — plus alt-text generation for accessibility.
3. **Narrative daily/weekly digests.** `report_spotting_today` today emits three static buckets of vehicle IDs per Telegram channel. With the same query set, an LLM summariser could produce a natural-language digest ("first sighting of set 25 since March; three sets still unspotted this week"), personalised per channel, and answer free-form questions over the ledger — the `free_search` filter and `spottingTrends` aggregations are already the retrieval primitives a text-to-query layer would target.

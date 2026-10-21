# Component: spotting

## 📌 Purpose & Scope

- **Core Responsibility:** Owns the community "vehicle sighting" ledger. A logged-in user records that an `operation.Vehicle` was seen on a date, in an operational state, at a place given as station(s), a depot, or GPS coordinates, optionally with photos and notes. Fleet status charts, "last spotted" data, and the daily Telegram digest are all derived from this ledger.
- **Domain/Layer:** Django business logic and persistence, exposed through Strawberry GraphQL (`rosak.schema.Query` / `Mutation` at `POST /graphql/`), Django admin, and Celery. No templates or REST views. Media ingestion is delegated to `common`'s `POST /upload/`.

## 🔌 Interface & Data Flow

### Inputs

**GraphQL queries** (`SpottingScalars`, mixed into root `Query`):

| Field | Notes |
| --- | --- |
| `events` | `strawberry_django.field(filters=EventFilter, order=EventOrder, pagination=True)`. The main listing. |
| `eventsCount` | `spotting.schema.resolvers.get_events_count`: bare `Event.objects.acount()`. It ignores `EventFilter`, so any filtered or paginated total is wrong. |

**`EventFilter`** (`spotting/schema/filters.py`): declarative lookups on `id`, `type`, `created` and `spotted` (datetime and date lookups), `notes`, `status`, `is_anonymous`, plus a nested `operation.VehicleFilter`. Five custom `filter_field`s carry logic:

- `has_notes`: `~Q(notes="")`.
- `different_status_than_vehicle`: `~Q(vehicle__status=F("status"))`. Finds sightings that contradict the vehicle's recorded status (the moderation predicate).
- `is_read`: subquery on `EventRead` for the requesting user. Returns `queryset.none()` for anonymous callers.
- `only_mine`: `Q(reporter_id=info.context.user.id)`.
- `free_search`: icontains across `notes`, both station `display_name`s, `vehicle.identification_no`, and `vehicle.nickname`.

**`EventOrder`**: `id`, `spotting_date`, `created`.

**Mutations** (`SpottingMutations`):

| Mutation | Input | Permissions |
| --- | --- | --- |
| `addEvent` | `EventInput` → `EventScalar` | `IsLoggedIn`. The reCAPTCHA check is commented out. |
| `deleteEvent` | `DeleteEventInput { id }` → `GenericMutationReturn` | `IsLoggedIn`, `IsRecaptchaChallengePassed` |
| `markAsRead` | `MarkEventAsReadInput { event_ids: [ID] }` → `GenericMutationReturn` | `IsLoggedIn`, `IsRecaptchaChallengePassed`. Writes `EventRead` with `ignore_conflicts=True`. |

`EventInput` fields: `spotting_date`, `vehicle: ID`, `status`, `type`, and optional `notes`, `run_number`, `wheel_status`, `origin_station`, `destination_station`, `location` (`generic.WebLocationInput`), `is_anonymous`. Station IDs are **`operation.StationLine` IDs**. `add_event` translates them to `Station` IDs, and only for `BETWEEN_STATIONS` and `AT_STATION`.

**Image upload** is not a spotting endpoint. The client calls `POST /upload/` (`common.views.GenericUpload`) with `upload_type=SPOTTING_EVENT`, `related_id=<event id>`, and `image`. The view requires `user.id == event.reporter_id` (403 otherwise) and stages a `common.TemporaryMedia` with `metadata.spotting_event_id`.

**Django signals consumed:** none. `Event` and `EventMedia` are written by `common.signals.convert_temporary_media_to_media` (`post_save` on `TemporaryMedia`).

### Outputs

- **`EventScalar`** (`@strawberry_django.type(models.Event)`): flat fields `id`, `created`, `spotting_date`, `notes`, `status`, `type`, `wheel_status`, `run_number`. Relations `vehicle: operation.Vehicle` and `origin_station` / `destination_station: operation.Station`. DataLoader-backed fields: `reporter: common.UserScalar` (`None` when `is_anonymous`), `is_read` (`IsLoggedIn`), `location: LocationEvent` (`None` for an anonymous event unless the viewer is its reporter or an admin; see below), `media_count`, `medias: [common.MediaScalar]` (each photo's `uploader` is `null` for an anonymous event unless the viewer is the uploader or an admin; see below), and `is_mine`.
- **`LocationEvent`**: `location` (PointField scalar), `accuracy`, `altitude`, `altitude_accuracy`, `heading`, `speed`.
- **Anonymous spottings hide their GPS.** `EventScalar.location` resolves to `null` (the whole `LocationEvent`, so `accuracy`, `altitude`, `heading` and `speed` go with the point) when `event.is_anonymous` and the viewer is neither the event's reporter nor an admin (`spotting.schema.resolvers.viewer_can_see_location`; admin means the Firebase `admin` claim, `rosak.permissions.has_admin_claim`). Non-anonymous events are unchanged. `EventScalar.location` is the only field of the schema that returns `LocationEvent`, so every path to an event (`events`, `Vehicle.spottings`, `UserScalar.spottings`, the `addEvent` payload) is covered by that one resolver, and `EventFilter` has no location lookup, so a filter cannot be used to bisect a hidden position. `AnonymousLocationVisibilityTests` pins both facts: a new field or filter that exposes coordinates fails them. The admin claim is an uncached Firebase call, so it is read through `common`'s `is_admin_from_user_loader` (one call per viewer per request, and none for logged-out viewers, reporters or non-anonymous events). The owner-or-admin test is `viewer_is_owner_or_admin`, which `common.UserScalar` also uses to keep anonymous spottings off a public profile's list and figures.
- **Anonymous spottings hide their photos' uploader.** The photo stays visible; `Media.uploader` (the reporter) resolves to `null` on `MediaScalar` and `MediaType` unless the viewer is the uploader or an admin: `spotting.schema.resolvers.viewer_can_see_uploader`, reading `anonymous_uploader_from_media_loader` (media id to uploader id for media of an anonymous `EventMedia`, one query per request), wired to the field by `common.schema.scalars.uploader_field()`. It covers `events { medias }`, `medias`, `media(id)` and the incident photo edges. `AnonymousPhotoUploaderTests` pins it.
- **Outbound side effect:** the daily digest, sent by `spotting.tasks.report_spotting_today` as Telegram HTML to each distinct channel (see `telegram_provider.md`).
- **Reverse consumers** (they read spotting data): `operation.schema.loaders` (`last_spotting_date_from_vehicle_loader`, `last_spotted_at_from_vehicle_loader`, `spotting_count_from_vehicle_loader`, `spottings_from_vehicle_loader`), `operation.schema.scalars` (`Vehicle.spottingTrends`, `Line.vehicleSpottingTrends`), `common.schema.loaders.spottings_from_user_loader`, `common.schema.scalars.UserScalar.spottings*`, `telegram_provider.models.TelegramSpottingEventLog`, `telegram_provider.handlers` (creates Events from bot commands), `telegram_provider.utils.get_daily_updates`, and `chartography` fleet-status aggregations.

### Dependencies

- **Outbound FKs:** `Event.reporter → common.User` (CASCADE), `Event.vehicle → operation.Vehicle` (CASCADE), `Event.origin_station` / `destination_station → operation.Station` (PROTECT), `Event.medias ↔ common.Media` (M2M through `EventMedia`), `Event.data_source → EventSource` (SET_NULL), `EventRead.reader → common.User`. `LocationEvent` extends `generic.models.WebLocationModel`.
- **Inbound FKs:** `telegram_provider.TelegramSpottingEventLog.spotting_event → spotting.Event`.
- **Libraries:** `strawberry` / `strawberry-django`, `django.contrib.gis` (PostGIS `PointField`), `django_choices_field.TextChoicesField`, `model_utils.TimeStampedModel`, `django.contrib.postgres.indexes.BTreeIndex`, `python-telegram-bot` (digest), `celery`, `firebase_admin`, and `django-advanced-filters` / `django-rangefilter` / `ordered-model` in admin.
- **Firebase bootstrap:** `SpottingConfig.ready()` calls `firebase_admin.initialize_app()`. It also raises `ImproperlyConfigured` when `GOOGLE_APPLICATION_CREDENTIALS` is set but is not a readable file. This catches a missing docker-compose bind mount, which Docker silently creates as a directory.

## ⚙️ Internal State & Logic

**Models** (`spotting/models.py`):

- `Event`: aggregate root, `TimeStampedModel`. `created` is the audit timestamp; `spotting_date` is the user-asserted sighting date. They are deliberately distinct.
- `LocationEvent`: GPS payload, FK to `Event` (not OneToOne). Loaders assume one row per event and keep the last one. `location` is non-null.
- `EventRead`: per-user read receipt, `UniqueConstraint(reader_id, event_id)`.
- `EventMedia`: explicit M2M through-table to `common.Media`.
- `EventSource`: lookup of ingestion channels, named after `SpottingDataSource` (`SITE`, `TELEGRAM`).

**Enums** (`spotting/enums.py`): `SpottingEventType` (`DEPOT`, `LOCATION`, `BETWEEN_STATIONS`, `JUST_SPOTTING`, `AT_STATION`); `SpottingVehicleStatus` (`IN_SERVICE`, `NOT_IN_SERVICE`, `DECOMMISSIONED`, `TESTING`, `NOT_SPOTTED`, `MARRIED`, `UNKNOWN`); `SpottingWheelStatus` (`FRESH`, `NEAR_PERFECT`, `FLAT`, `WORN_OUT`, `WORRYING`); `SpottingDataSource` (`SITE`, `TELEGRAM`).

**Type and station invariant, enforced in the database:** `CheckConstraint` `spotting_event_value_relevant`:

- `BETWEEN_STATIONS`: both stations set, and distinct.
- `AT_STATION`: origin set, destination null.
- `DEPOT`, `JUST_SPOTTING`, `LOCATION`: both stations null.

Read paths use two `BTreeIndex`es: `(vehicle, -spotting_date)` and `(vehicle, run_number, -spotting_date)`.

**Deletion policy** is written twice. `Event.auser_deletion()` raises unless the caller is the reporter and the event is under 3 days old. It is used only by the Telegram `/delete` handler. The `deleteEvent` mutation expresses the same rule as a queryset filter (`reporter_id`, `created__gte=now()-3d`) and returns `ok=False` instead of raising. Keep the two in sync, or move the rule to one model method.

**N+1 avoidance:** `SpottingContextLoaders` (`spotting/schema/loaders.py`) is registered under key `"spotting"` in `rosak.context.ContextLoaders`. It holds six loaders: `reporter_from_event_loader` (filters `is_anonymous=False`, so anonymity is enforced in the loader), `is_read_from_event_loader` (composite `(event_id, reader_id)` key), `location_event_from_event_loader` (joins the event, so the resolver can apply the anonymity rule without a second query; the rule itself is per viewer and so lives in the resolver), `media_count_from_event_loader`, `media_from_event_loader`, and `anonymous_uploader_from_media_loader` (media id to uploader id when the media belongs to an anonymous event, else `None`; the viewer check lives in `viewer_can_see_uploader`).

**Media pipeline:** owned by `common` (upload, NSFW check, Discord CDN conversion). See `common.md`. Spotting-specific details: conversion re-checks `uploader_id == event.reporter_id` (raises on mismatch) and then creates `EventMedia`. Telegram-staged video from untrusted uploaders is held as `AWAITING_REVIEW` until an admin runs `/approve`.

**Celery** (`spotting/tasks.py`): one task, `report_spotting_today`. Beat: `crontab(hour="0", minute="0")` in `rosak/celery.py`, which is **00:00 server time**. It is a sync `bind=True` task (Celery does not await coroutine tasks). The spotting date is `telegram_provider.utils.effective_spotting_date(datetime.now(ZoneInfo(TIME_ZONE)))`, so a run before the 03:00 service-day cutoff (the 00:00 beat, even if the worker is late) reports the previous day. It iterates `Line.objects.order_by("telegram_channel_id", "code").distinct("telegram_channel_id")`, skips null or empty channel ids, and sends one digest per distinct channel. Several lines may share a channel, so the digest is rendered for the channel's first line by `code`, through `telegram_provider.utils.get_daily_updates(...)`, and lists only that line's vehicles. It is sent with `async_to_sync(utils.send_message)`, so the send is audited. Digest buckets are described in `telegram_provider.md`.

**Schema evolution** (17 migrations, `spotting/migrations/`): initial model; anonymity and status rework (0003 to 0005); `(vehicle, spotting_date)` index (0006); read receipts (0007); `LocationEvent` and altitude (0008 to 0009); repeated tightening of `value_relevant` (0004, 0010); `run_number` (0011); `0012_modify_spotting_types` (data migration reshaping the type vocabulary); `EventMedia` M2M (0013); `wheel_status` (0015); `EventSource`, `Event.data_source`, and source `data` (0016 to 0017).

**Admin** (`spotting/admin.py`): `EventAdmin` with advanced filters, date-range filters, `list_editable = [run_number, notes]`, a read-only media thumbnail widget, and a `TelegramSpottingEventLog` inline. `LocationEventAdmin` uses `generic.views.GeometricForm`. `EventRead`, `EventMedia`, and `EventSource` are not registered.

**Dead code:** `spotting/serializers.py` (`SnippetSerializer`) has no importers.

## 🧩 Extension Points & Hooks

- **`@strawberry_django.filter_field` on `EventFilter`**: the established way to add server-side query semantics. Context-aware filters receive `info` and may return `(queryset, Q)`. New filters need no schema-wide change.
- **`SpottingContextLoaders` dict**: add a `DataLoader` key and a matching `@strawberry.field` on `EventScalar` to add a batched relation without touching `rosak/context.py`.
- **`EventSource` plus `SpottingDataSource`**: the seam for new ingestion channels (a Discord bot, an OCR importer, an open API) without schema migrations. The `EventSource.data` JSON column is the per-source payload escape hatch.
- **`TemporaryMediaType` plus `TemporaryMedia.metadata`**: the moderation pipeline is generic over upload types. New attachment kinds plug in as new `upload_type` branches.
- **`SpottingConfig.ready()`**: the natural place to register `post_save` signals on `Event`. None exist today, so push notifications or leaderboard fan-out would attach here.
- **`common.ClearanceType`**: new spotting-specific clearances can gate mutations through new `rosak.permissions` classes.
- **Celery beat**: `report_spotting_today` is the template for further scheduled digests.

## 💡 Potential Feature Opportunities

1. **Mark an event as unread.** `markAsRead` is `IsLoggedIn`, so users can mark their own sightings read. The `EventRead` model, the loader, `EventScalar.is_read`, and `EventFilter.is_read` already exist. A companion `markAsUnread` mutation (delete the matching `EventRead` rows) is about ten lines in the same class and needs no migration.
   **Readiness:** `Ready`.

2. **An `editEvent` mutation, with the contribution window in one place.** Today the only correction path is destructive: a user who mistypes `run_number`, picks the wrong `status`, or mis-taps `wheel_status` must delete and re-file. That loses the original `created` timestamp and any attached media. The 3-day rule is also written twice (see Deletion policy). `TimeStampedModel` already provides `Event.modified`, which is not exposed on `EventScalar`.
   **Readiness:** `Partially ready`. There is no `EditEventInput` or `edit_event`. Editing `type` or the station pair must re-satisfy `spotting_event_value_relevant`, so the mutation needs the same `StationLine → Station` translation as `add_event`. Hoist the window rule into one model method (for example `Event.is_within_edit_window`) and have both the mutation and `auser_deletion` use it. Files: `spotting/models.py`, `schema/inputs.py`, `schema/schema.py`, `schema/scalars.py`.

3. **A moderation queue for sightings that contradict the fleet record.** `EventFilter.different_status_than_vehicle` already expresses "this report disagrees with `Vehicle.status`", and `EventAdmin` has triage-friendly `list_editable` and advanced filters. Nothing records an outcome, so dismissed items resurface and two reviewers can duplicate work. A resolution state turns the filter into a workflow. It is also the natural consumer of the digest's "Spotted Today, to review" bucket.
   **Readiness:** `Partially ready`. The filter is live but ungated, so any caller, including anonymous, can use it. Add `Event.review_state` plus `reviewed_by` and `reviewed_at` (migration), a `review_state` lookup on `EventFilter`, a staff-gated mutation, and an admin action. Also register `EventRead`, `EventMedia`, and `EventSource` in admin so staff can inspect them.

4. **Contributor leaderboards, streaks, and "sets you have never spotted".** The aggregation groundwork exists. `common.UserScalar` resolves `favourite_vehicles`, `with_most_entries`, `spottings_count`, and `spotting_trends`. `operation.Vehicle` exposes `last_spotting_date` and `spottingCount`. Streaks are date arithmetic over `spotting_date`. "Gaps in your collection" is an anti-join between a line's vehicles and the user's events. This is a plausible retention loop, and it needs no new data.
   **Readiness:** `Partially ready`. Per-user fields cannot rank users against each other, so cross-user resolvers are needed (`spotting/schema/resolvers.py` holds only `get_events_count`). Blockers:
   - `eventsCount` ignores filters. The commented `ListConnectionWithTotalCount` in `spotting/schema/schema.py` is the intended fix.
   - `VehicleFilter` (`operation/schema/filters.py`) exposes only `id` and `status`. "Never spotted by me" needs a context-aware `filter_field`.

5. **Map view of sightings, and GPS on every event type.** `LocationEvent` already stores a non-null PostGIS point plus accuracy, altitude, heading, and speed. `operation.StationFilter.location` shows the pattern a geo filter would copy (`location__distance_lt` with `Distance(km=...)`). A viewport or "near me" query would make `LOCATION` and `JUST_SPOTTING` events meaningful.
   **Readiness:** `Not ready`, for three reasons:
   - `LocationEvent.event` is a plain FK, so one `Event` can have many location rows. The loader silently keeps the last one. De-duplicate, then migrate to `OneToOneField`.
   - Nothing requires coordinates for `type=LOCATION`. The `value_relevant` constraint covers only the station columns, and `add_event` creates a `LocationEvent` only when `location` is given. Extend the constraint or validate in the mutation.
   - Telegram ingestion captures no coordinates (`# TODO: Location to determine spotting type` in `telegram_provider/handlers.py`).

   Only then add a radius or bbox `location` filter to `EventFilter`, plus a distance ordering in `spotting/schema/orderings.py`.

## 💡 Potential AI Feature Opportunities

1. **Anomaly and plausibility scoring on submission.** The table holds vehicle, date, run number, wheel status, GPS point, and station pair, and `different_status_than_vehicle` already encodes "contradicts the fleet record". A model over the `(vehicle, -spotting_date)` history could flag physically impossible sightings (one vehicle at two distant stations minutes apart), wrong-line reports, or copy-pasted run numbers. It would write a score into a new field that feeds the admin triage queue.
2. **Vision-assisted auto-fill and richer moderation.** Photos already pass through a Celery task that opens them with Pillow and reads EXIF. An image model there could OCR the `identification_no` or run number to prefill `EventInput`, classify `wheel_status` from bogie shots, and add a multi-label safety check with a rejection reason to the existing NSFW classifier.
3. **Narrative digests.** `report_spotting_today` emits three static buckets of vehicle IDs per channel. The same queries could feed an LLM that writes a per-channel summary ("first sighting of set 25 since March; three sets still unspotted this week"). The `free_search` filter and `spottingTrends` aggregations are already the retrieval primitives a text-to-query layer would use.

# MISTAKES.md — rosak_backend Known Defects & Traps

> Compiled from `docs/APPS.md` § Known Defects & Traps (lines 282–306) and the per-app component docs in `docs/components/*.md`.
> Every entry is a proven bite — either already fixed or still live. Grouped by component so you can scan what will break you when you touch that app.
> Dates are catalogue date (Phase 1 audit) unless a fix commit exists, in which case both are shown.

---

## common

### [2026-08-24] common: NSFW moderation bypassed — all uploads convert unchecked — FIXED (2026-08-24) `1e2a421`

**Problem**: `common/signals.py` had the `check_temporary_media_nsfw` import and `apply_async` call commented out. Every `TemporaryMedia(PENDING)` went straight to `convert_temporary_media_to_media_task` with no moderation check (`docs/APPS.md:288`, `docs/components/common.md:24,73`).
**Root Cause**: Commented gate left in place during Discord migration; orphaned task `check_temporary_media_nsfw` had no caller.
**Fix**: Re-enabled `check_temporary_media_nsfw.apply_async` for non-trusted uploaders in `common/signals.py`; trusted path `TRUSTED_MEDIA_UPLOADER → TRUSTED_CLEARED` preserved. Commit `1e2a421` `fix(common): re-enable NSFW moderation in upload pipeline` (2026-08-24).
**Prevention**: Gate moderation on `TemporaryMediaType` + `TRUSTED_MEDIA_UPLOADER` clearance; add integration test that `PENDING` from untrusted user reaches `BLOCKED`/`CLEARED` via classifier mock.

### [2026-08-24] common: `get_default_start_time()` crashes on YEAR/MONTH/WEEK — FIXED (2026-08-24) `bb1e519`

**Problem**: `common/utils.py:get_default_start_time()` did `today.month = 1` / `today.day = 1` on immutable `datetime.date` — `YEAR`, `MONTH`, `WEEK` branches raise `AttributeError: attribute 'month' of 'datetime.date' objects is not writable`. Only `DAY` worked, so every caller hardcoded `DateGroupings.DAY` (`docs/APPS.md:292`, `docs/components/common.md:76`, `docs/components/generic.md:208`).
**Root Cause**: Mutating immutable date object; only `DAY` branch exercised in production, so bug was latent.
**Fix**: Already uses `today.replace(month=..., day=...)`. Commit `bb1e519` `refactor(graphql): Migrate Phase 1 leaf inputs and utils from UNSET to Maybe[T]` (2026-08-19), catalogued FIXED 2026-08-24. Unlocks monthly/weekly/yearly analytics across `common` + `operation` + `chartography`.
**Prevention**: Add unit test exercising each `DateGroupings` branch; exhaustive switch already raises `RuntimeError` on unknown member — keep it.

### [2026-08-24] common: `ImgurStorage` still on the hot path for every upload

**Problem**: `common/tasks.py:202` creates `Media` with `file=ContentFile(temp_media.file.url, ...)` which routes through `ImgurStorage._save` and makes a live Imgur API call for every upload, despite `Media.file` being marked `# TODO: Deprecate` and Discord CDN being the real host (`docs/APPS.md:293`, `docs/components/common.md:72,95`).
**Root Cause**: Migration from Imgur → Discord left `Media.file` wired as write path; no one removed the five call sites (`STORAGE = ImgurStorage()`, `MediaMixin.__str__`, `add_width_height_to_media_task` filter, `medias_group_by_period ~Q(file="")`, `MediaAdmin.fields`).
**Fix**: _Not fixed._ Requires re-host backfill for pre-`0013` rows (fetch `i.imgur.com/<file>` → Discord webhook → fill `file_id`/`file_name`), then drop `Media.file` column and delete `imgur_field.py`, `imgur_storage.py`, `management/commands/get_imgur_token.py`.
**Prevention**: Feature-flag the storage backend; block new `Media.file` writes behind flag and alert on `ImgurStorage._save` calls after cutoff.

### [2026-08-24] common: `ImgurStorage` silently degrades on bad credentials

**Problem**: `ImgurStorage.__init__` and module-level `ImgurClient` swallow all exceptions and print `functionality disabled`; eight `IMGUR_*` settings default to `""` (`rosak/settings.py:357-364`), so a deployment without Imgur credentials dies with `AttributeError` inside `convert_temporary_media_to_media_task`'s broad `except Exception` and only increments `fail_count` — no upload can succeed despite Discord being the host (`docs/components/common.md:72`).
**Root Cause**: Fail-open init plus broad exception that hides the root error.
**Fix**: _Not fixed._ Make init fail loudly if `Media.file` is still required; otherwise remove Imgur path entirely (see previous entry).
**Prevention**: Validate required credentials at `check` time; never swallow storage init errors; replace broad `except Exception` with typed handling plus explicit dead-letter.

### [2026-08-24] common: `TemporaryMediaAdmin.prettified_metadata` crashes + `RETRY_ELAPSED` never assigned

**Problem**: `TemporaryMediaAdmin` declares `prettified_metadata` calling `self.prettify_json()` but inherits `admin.ModelAdmin` not `generic.admin.JsonPrettifyAdminMixin`, so the admin page raises `AttributeError` and never `return`s; `TemporaryMediaStatus.RETRY_ELAPSED` is declared (`common/enums.py:23`) and assigned nowhere — permanently dead uploads sit in `PENDING` indistinguishable from fresh rows (`docs/APPS.md:294`, `docs/components/common.md:99`).
**Root Cause**: Missing mixin plus dead status enum never wired into retry cutoff.
**Fix**: _Not fixed._ Inherit `JsonPrettifyAdminMixin` and `return` the highlighted HTML; in the re-drive loop (`common/tasks.py:255-264`) assign `RETRY_ELAPSED` at `fail_count >= 5` and persist exception string into `metadata` JSON.
**Prevention**: Admin smoke test hitting every `ModelAdmin` change view; exhaustive status-transition test that asserts every enum member is reachable.

### [2026-08-24] common: `Media` scalar non-null mismatch + admin search_fields broken

**Problem**: `MediaScalar`/`MediaType` declare `width: int` / `height: int` non-null while `Media.width`/`height` are `null=True, default=None` — exposing more rows raises non-null resolution errors on legacy media. `MediaAdmin` and `TemporaryMediaAdmin` use `search_fields = ["uploader"]` which is a FK, not a text field, so admin search raises `FieldError` (`docs/components/common.md:93,99`).
**Root Cause**: Scalar nullability not matched to model; admin `search_fields` not using lookup path `uploader__nickname`.
**Fix**: _Not fixed._ Make scalar widths nullable `Optional[int]` or backfill dimensions; fix `search_fields` to `["uploader__nickname"]`.
**Prevention**: Contract test asserting model nullability matches Strawberry scalar nullability.

### [2026-08-24] common: `FeatureFlag` missing row silently disables + GC gated on same flag

**Problem**: `should_upload_media()` treats missing `FeatureFlag` row as disabled (`feat_flag is not None and feat_flag.enabled`), so fresh env with no fixture is silently off. `cleanup_temporary_media_task` early-returns on that same flag, so disabling upload also halts 30-day `TO_DELETE` GC — staging bucket grows unbounded (`docs/components/common.md:101`).
**Root Cause**: Ambiguous "missing = off" plus coupling upload gate to garbage collection.
**Fix**: _Not fixed._ Seed one row per `FeatureFlagType` via data migration; split GC flag from upload flag.
**Prevention**: Data migration creating flag rows on deploy; separate `IMAGE_UPLOAD` vs `STORAGE_GC_ENABLED` flags.

---

## incident

### [2026-08-24] incident: `StationIncident` UniqueConstraint missing condition — FIXED (2026-08-24) `1e2a421`

**Problem**: `VehicleIncident` guards `UniqueConstraint(fields=["is_last","vehicle"], condition=Q(is_last=True))` but `StationIncident` declared `UniqueConstraint(fields=["is_last","station"])` without `condition` — a station could hold at most one historical (`is_last=False`) incident before `IntegrityError` (`docs/APPS.md:289`, `docs/components/incident.md:72`).
**Root Cause**: Copy-paste omission; constraint copied without condition.
**Fix**: Added `condition=Q(is_last=True)` to `StationIncident`. Commit `1e2a421` `fix(incident): add condition=Q(is_last=True) to StationIncident UniqueConstraint` (2026-08-24). Migration `RemoveConstraint` + `AddConstraint` required on legacy data.
**Prevention**: Model constraint review checklist; test creating two historical incidents for same station.

### [2026-08-24] incident / operation: Dual `Line ↔ CalendarIncident` join tables — GraphQL field permanently empty

**Problem**: `CalendarIncident.lines` (`related_name="incidents"`, migration `0013`) and `operation.Line.calendar_incidents` are two separate M2M join tables. Admin `filter_horizontal` edits the former; GraphQL `Line.calendarIncidents` reads the latter, so that field is expected to be permanently empty (`docs/APPS.md:290`, `docs/components/incident.md:71`, `docs/components/operation.md:48`).
**Root Cause**: Both sides declared `ManyToManyField` to each other instead of one side using reverse accessor; `through` left commented on `Line`.
**Fix**: _Not fixed._ Consolidate on `Line.incidents` reverse accessor; remove `Line.calendar_incidents` field.
**Prevention**: Single source of truth for cross-app M2M; forbid duplicate M2M declarations across apps via `tach` rule.

### [2026-08-24] incident: `CalendarIncidentFilter.date` bare assert + month off-by-one

**Problem**: Range width enforced with `assert … <= timedelta(days=60)` — surfaces as 500 and stripped under `python -O`; `month` branch does `month__lte=value.month.exact + 1` assuming 0-indexed JS month (`docs/components/incident.md:21`).
**Root Cause**: `assert` used for validation; JS month indexing leaked into Python.
**Fix**: _Not fixed._ Replace `assert` with `GraphQLError`/`ValidationError`; fix month arithmetic to `__month=value.month.exact`.
**Prevention**: Ban bare `assert` for request validation (repo convention); add filter unit tests for 60-day boundary and month exact.

### [2026-08-24] incident: `last_updated` N+1 hotspot — 3 queries per node

**Problem**: `CalendarIncidentScalar.last_updated` re-fetches the row then `.count()` + ordered slice on `chronologies` to compute `max(modified)`. Three extra queries per node invisible to `DjangoOptimizerExtension` (`docs/components/incident.md:36,68`).
**Root Cause**: Resolver not using DataLoader/annotate; per-node sync fetch.
**Fix**: _Not fixed._ Annotate with `Greatest(F("modified"), Max("chronologies__modified"))` or batch via DataLoader.
**Prevention**: Load-test with `assertNumQueries`; forbid per-node re-fetch in resolvers.

### [2026-08-24] incident: `medias_from_calendar_incident_loader` discards ordering and dedupes

**Problem**: `batch_load_medias_from_calendar_incident` returns a `set` per key though field is typed `List[MediaScalar]` — media silently de-duplicated and `CalendarIncidentMedia.timestamp` ordering discarded (`docs/components/incident.md:68`).
**Root Cause**: Wrong collection type for ordered M2M through table.
**Fix**: _Not fixed._ Return `list` preserving through-table ordering.
**Prevention**: Type-check loader return shapes; test that media order matches admin inline order.

---

## spotting

### [2026-08-24] spotting: `markAsRead` gated `IsAdmin` — per-user read state unreachable — FIXED (2026-08-24) `1e2a421`

**Problem**: `EventScalar.is_read` / `EventFilter.is_read` are user-scoped and `IsLoggedIn`, but `markAsRead` required `IsAdmin` (`spotting/schema/schema.py:180`) — complete feature switched off for non-admins (`docs/APPS.md:295`, `docs/components/spotting.md:34,93`).
**Root Cause**: Permission copy-paste; `IsAdmin` left on mutation that writes per-user `EventRead`.
**Fix**: Ungated from `IsAdmin` to `IsLoggedIn`; resolver already uses `info.context.user.id` + `abulk_create(ignore_conflicts=True)`. Commit `1e2a421` `fix(spotting): ungate markAsRead mutation from IsAdmin to IsLoggedIn` (2026-08-24).
**Prevention**: Permission matrix test asserting each mutation's required clearance.

### [2026-08-24] spotting: `eventsCount` unfiltered + `with_most_entries` IndexError

**Problem**: `spotting.schema.resolvers.get_events_count` is bare `Event.objects.acount()` ignoring `EventFilter` — paginated UI shows wrong total. `UserScalar.with_most_entries` indexes `[0]` into aggregate queryset and raises `IndexError` for user with zero events (`docs/APPS.md:296`, `docs/components/spotting.md:17,103`).
**Root Cause**: Resolver not reusing filter Q; missing empty-queryset guard.
**Fix**: _Not fixed._ Pass filtered queryset into count; guard `with_most_entries` with empty check. Commented `ListConnectionWithTotalCount` is intended fix.
**Prevention**: Always derive count from same filtered queryset; test zero-event user profile.

### [2026-08-24] spotting: `CheckConstraint` never requires coordinates for `LOCATION`

**Problem**: `spotting_event_value_relevant` governs only station columns; `type=LOCATION` can be saved with no `PointField` (`docs/APPS.md:297`, `docs/components/spotting.md:67,106`).
**Root Cause**: Constraint modeled station invariants only; GraphQL `add_event` creates `LocationEvent` only if `input.location != UNSET`, so type is decorative.
**Fix**: _Not fixed._ Extend `CheckConstraint` or validate in mutation to require `LocationEvent` row for `type=LOCATION`; enforce OneToOne migration from FK after dedup.
**Prevention**: DB-level invariant tests for each `SpottingEventType` variant.

### [2026-08-24] spotting / telegram_provider: `get_daily_updates()` ignores its `spotting_date` argument

**Problem**: `telegram_provider.utils.get_daily_updates(line_id, spotting_date)` overwrites `spotting_date` with `date.today()` on first line; `spotting.tasks.report_spotting_today` passes `yesterday = date.today() - 1` but digest reports today (`docs/APPS.md:291`, `docs/components/spotting.md:75,91`, `docs/components/telegram_provider.md:91`).
**Root Cause**: Stale overwrite left after refactor; Beat job intent (03:00 yesterday) silently ignored.
**Fix**: _Not fixed._ Remove overwrite and honor argument; pass timezone-aware `yesterday` explicitly.
**Prevention**: Unit test asserting digest date equals injected date, not `today()`.

### [2026-08-24] spotting: `LocationEvent` FK not OneToOne + divergent deletion rules

**Problem**: `LocationEvent.event` is `ForeignKey` not `OneToOne`; `batch_load_location_event_from_event` keeps last row silently. Deletion rule duplicated: `Event.auser_deletion()` raises vs `deleteEvent` mutation returns `ok=False` with subtly different 3-day window (`created__gte=now()-3d`) (`docs/components/spotting.md:60,69,106`).
**Root Cause**: FK chosen without uniqueness; deletion logic expressed twice.
**Fix**: _Not fixed._ Migrate to `OneToOneField` after dedup; hoist window into `Event.is_within_edit_window()` used by both paths.
**Prevention**: Choose `OneToOneField` for 1:1 payloads; single model method for policy, not queryset filter duplication.

---

## operation

### [2026-08-24] operation: Write API imports non-existent `operation.schema.enums`

**Problem**: Commented `operation/schema/inputs.py` does `from operation.schema.enums import AssetType` but module does not exist — enums live in `operation/enums.py`. `StationInput.internal_representation` is a `StationLine` field misplaced on `Station`; no `VehicleInput` exists at all (`docs/APPS.md:298`, `docs/components/operation.md:80`).
**Root Cause**: Refactor moved enums but inputs stub not updated; `Station` vs `StationLine` confusion.
**Fix**: _Not fixed._ Repoint import to `operation.enums` or use generated enum; drop `internal_representation` from `StationInput` or nest `StationLine` rows; add `VehicleInput`/`VehiclePartialInput`.
**Prevention**: Keep commented scaffolding importable under `if TYPE_CHECKING`; CI `ruff check` on commented files.

### [2026-08-24] operation: `StationLine` has no ordinal — lexicographic ordering breaks route order

**Problem**: `StationLine.Meta.ordering = ["internal_representation"]` sorts lexicographically (`KJ10` before `KJ2`); `StationLine` has no `order` field, so `Line.station_lines` cannot render travel order for strip maps / "next stations" (`docs/APPS.md:299`, `docs/components/operation.md:71`).
**Root Cause**: Missing `OrderedModel` despite `django-ordered-model` already being a dependency for `incident`.
**Fix**: _Not fixed._ Inherit `OrderedModel` with `order_with_respect_to="line"`, data-migrate `order` from numeric tail of `internal_representation`, switch admin to `OrderedTabularInline`.
**Prevention**: Explicit route order field; never rely on code string ordering for sequence.

### [2026-08-24] operation: `spotting_count_from_vehicle_loader` key collision on date window

**Problem**: `batch_load_spotting_count_from_vehicle` aliases aggregate as `Count(filter=Q(...))` on `key[0]` only while key is `(vehicle_id, Q(date_filter))` — two different date windows for same vehicle in one request collide and return same count (`docs/APPS.md:304`, `docs/components/operation.md:51`).
**Root Cause**: Batch key's filter part not included in SQL alias.
**Fix**: _Not fixed._ Alias on full composite key or issue separate aggregates per distinct `(vehicle_id, Q)` key.
**Prevention**: Loader unit test with same vehicle queried for two windows in one request.

### [2026-08-24] operation: DataLoader batch assumes uniform filter + scalar field mismatches

**Problem**: `batch_load_vehicle_from_line` reads `keys[0][1]` assuming every key in batch shares same `spotted_today`; `VehicleType` scalar declares `info: str` vs model `description`; `Asset.stations`/`StationLine.lines` declare plural list over singular FKs; `LineAdmin` assigns `list_editable` twice, second wins and drops `status` inline editing (`docs/components/operation.md:52`).
**Root Cause**: Batch ergonomic shortcut; copy-paste scalar naming; duplicate attribute overwrite.
**Fix**: _Not fixed._ Group keys by `spotted_today` before single query; rename scalar fields to match model; fix `list_editable`.
**Prevention**: Never index `keys[0]` for per-key state; lint for duplicate class attribute assignment.

---

## telegram_provider

### [2026-08-24] telegram_provider: `handlers.spot` provenance missing chat filter — cross-chat collision

**Problem**: `spot` joins `TelegramSpottingEventLog` via `telegram_log__payload__message__message_id` with no `__chat__id` filter (unlike `/delete`), so `message_id` (unique only per chat) can bind spotting to another chat's message (`docs/APPS.md:300`, `docs/components/telegram_provider.md:64,119`).
**Root Cause**: Incomplete JSONB lookup; `payload` has no DB index (`Meta` absent).
**Fix**: _Not fixed._ Add `payload__message__chat__id` filter; add `UniqueConstraint(spotting_event, telegram_log)` and GIN/expression index on `payload`.
**Prevention**: Always qualify Telegram `message_id` with `chat_id`; index JSONB lookups used in prod queries.

### [2026-08-24] telegram_provider: Unbounded retry + silent error reporting + blocking I/O

**Problem**: `utils.infinite_retry_on_error` is `while True` with 10s `sleep` — can pin worker forever; `error_handler` only `print`s while `TELEGRAM_ADMIN_CHAT_ID` is unused; `/dadjoke` does blocking `requests.get` inside async handler, blocking event loop (`docs/components/telegram_provider.md:48,90,91`).
**Root Cause**: Ad-hoc resilience plus commented-out admin alert path.
**Fix**: _Not fixed._ Bound retry with backoff + dead-letter `TelegramLogs(direction=OUTBOUND)` row; wire `error_handler` to send to `TELEGRAM_ADMIN_CHAT_ID`; replace `requests` with shared `app_config.httpx_client`.
**Prevention**: Bounded retry policy; centralised `send_message` helper that logs `OUTBOUND` and handles 4096-char split in one place.

---

## chartography

### [2026-08-24] chartography: `SourceCustomLine` admin mapping unreachable + MTREC task incomplete

**Problem**: `SourceCustomLine.mapped_lines` uses explicit `through=SourceCustomLineLineMapping`, so Django omits it from admin form; `SourceCustomLineLineMapping` unregistered and `SourceCustomLineAdmin` has no inline — admin-editable reconciliation escape hatch is unreachable. `aggregate_line_vehicle_status_mtrec_task` accepts neither `force` nor `triggered_by_id`, and no mutation can trigger it (`docs/APPS.md:301`, `docs/components/chartography.md:76,82`).
**Root Cause**: Explicit through not paired with inline; MTREC path not given same kwargs as MLPTF path.
**Fix**: _Not fixed._ Add `TabularInline` for through model; give MTREC task `force`/`triggered_by_id` plus sibling mutation; wire `force=True` to `delete` conflicting `Snapshot` in `transaction.atomic()` (currently `force` is dead parameter and `bulk_create(ignore_conflicts=True)` discards corrections).
**Prevention**: Admin smoke test creating mapping via UI; mutation parity test for both sources.

### [2026-08-24] chartography: Hardcoded PK map + implicit datetime coercion + assert guard

**Problem**: MTREC `short_code_line_ids_map` hardcodes numeric `operation.Line` PKs (`KGL→[2]`, `Komuter→[13,14]`) — rots on reseeding. `Snapshot.date` (`DateField`) assigned `datetime` (`now() - timedelta(...)`) relies on implicit coercion, timezone-sensitive at day boundaries. `Snapshot.url` never populated. Guard is `assert isinstance(line_ids, list)` stripped under `python -O` (`docs/components/chartography.md:52,57`).
**Root Cause**: Seed-data assumptions baked into code; strict validation left as assert.
**Fix**: _Not fixed._ Always write `custom_line_id` and resolve via `custom_line__mapped_lines` join seeded by data migration; use `.date()` explicitly in defined timezone; raise explicit exception for unknown short code; populate `Snapshot.url`.
**Prevention**: Forbid hardcoded PKs; validate external payload shapes with explicit errors, not `assert`.

---

## reporting

### [2026-08-24] reporting: Missing `reporting/schema/enums.py` + plain `TextField` not enum

**Problem**: Commented `reporting/schema/filters.py:7` and `inputs.py:7` do `from reporting.schema.enums import ReportType` but file does not exist; `Report.type` is `TextField(choices=...)` so `strawberry.auto` renders `String` not `ReportType` enum (`docs/APPS.md:302`, `docs/components/reporting.md:21,76`).
**Root Cause**: Scaffolded GraphQL layer never completed; model used plain choices instead of `TextChoicesField`.
**Fix**: _Not fixed._ Create `@strawberry.enum` wrapper over `reporting.enums.ReportType` per `generic/schema/enums.py`; change `Report.type` to `TextChoicesField(choices_enum=ReportType)`.
**Prevention**: Generate Strawberry enum from model field; CI import-check even for dormant apps.

### [2026-08-24] reporting: `ReportFilter.filter_types` wrong field + ballot stuffing

**Problem**: `ReportFilter.filter_types` filters `report_type__in` while model field is `type`; no `UniqueConstraint` on `Vote(report, user)` so repeated `createVote` stuffs ballot; same missing uniqueness on `ReportMedia`/`ReportResolution` allows duplicate attachments/links (`docs/APPS.md:305`, `docs/components/reporting.md:54,78`).
**Root Cause**: Field rename not propagated to filter; constraints never added (compare `operation.AssetMedia` which has uniqueness).
**Fix**: _Not fixed._ Change filter to `type__in`; add `UniqueConstraint(fields=["report","user"])` on `Vote` plus through-table uniqueness; use idempotent `toggle_vote(report_id, is_upvote)` deriving `user_id` from `info.context.user.id` with `IsLoggedIn+IsRecaptcha`.
**Prevention**: Unique constraint on every vote/through table; filter field name test.

### [2026-08-24] reporting: Drafted mutations missing permissions + voter identity spoofable

**Problem**: Auto-generated `delete_reports` / `delete_vote` carry no `permission_classes`; `VoteInput.user_id` and `ReportInput.reporter_id` are client-supplied — any caller can vote/file as any user (`docs/components/reporting.md:78`).
**Root Cause**: Scaffold left without authz.
**Fix**: _Not fixed._ Derive voter/reporter server-side from `info.context.user.id`; gate all mutations `IsLoggedIn+IsRecaptcha` and owner-delete checks.
**Prevention**: Never trust client-supplied `user_id`; authz review for every mutation.

---

## generic

### [2026-08-18] generic: `GeoMultiPoint` duplicate GraphQL type name — FIXED (2026-08-18) `c318fd4`

**Problem**: `generic/schema/scalars.py:40` declared `GeoMultiPoint = strawberry.scalar(NewType("GeoLineString", ...))` — reused `GeoLineString` GraphQL name, so referencing both scalars in one schema fails `duplicate type name` (`docs/APPS.md:306`, `docs/components/generic.md:117`).
**Root Cause**: Copy-paste of `NewType` string.
**Fix**: Changed to `NewType("GeoMultiPoint", Tuple[GeoPoint])`. Commit `c318fd4` `dev: Add basic tests to prepare for django 5` (2026-08-18), catalogued FIXED 2026-08-24. Latent only because neither scalar was used.
**Prevention**: Test that `strawberry.Schema(query=Query)` builds with all scalars referenced.

### [2026-08-24] generic: `GeometricForm` dead `required` + Meta mutation order-dependent + `longitude==0` dropped

**Problem**: `GeometricForm.required` is `None` (falsy) but `latitude`/`longitude` built in parent class body with `required=required` while still `None` — subclass `required=False` never read. Subclasses configure by mutating parent's shared `GeometricForm.Meta` (e.g. `Meta.widgets={"location": HiddenInput()}` in `incident` but commented out in `spotting`/`operation`), so whether `location` renders hidden depends on import order. `clean()` does `if latitude and longitude` — legitimate `longitude==0` (prime meridian) silently dropped (`docs/APPS.md:303`, `docs/components/generic.md:82,168`).
**Root Cause**: Class-attribute mutation not per-subclass `Meta`; truthiness check instead of `is not None`.
**Fix**: _Not fixed._ Move model/widget config into per-subclass `Meta` or `__init_subclass__` hook; build `latitude`/`longitude` fields in `__init__` from `self.required`; change `clean()` to `if latitude is not None and longitude is not None`.
**Prevention**: Never mutate parent `Meta`; add test case with `longitude=0`.

### [2026-08-24] generic: `WebLocationInput` UNSET unreachable + empty schema roots + dead code

**Problem**: `WebLocationInput` fields are `Optional[float]` with no default — Strawberry renders nullable-but-required, so `if input.location != strawberry.UNSET` branch in `spotting/schema/schema.py:125-155` is unreachable. `GenericScalars`/`GenericMutations`/`PublicSpottingStats` are empty `@strawberry.type` with no fields — wiring them fails schema construction. `generic/types.py` `Point2D` TypedDicts unused; `generic/schema` has no `__init__.py` (implicit namespace); `generic/tests.py` 0 bytes — primitives used by five apps have no coverage (`docs/components/generic.md:32,110,118`).
**Root Cause**: Incremental scaffolding left incomplete.
**Fix**: _Not fixed._ Give each `WebLocationInput` field `= strawberry.UNSET`; add `__init__.py`; promote `Point2D_SearchField` to real `@strawberry.input` with shared `Q`-builder for point-radius search (needed by `operation`, `spotting`, `incident`).
**Prevention**: Test that `strawberry.UNSET` branches are reachable; require `__init__.py` for every `schema` package.

---

## rosak (project)

### [2026-08-24] rosak: Single async GraphQL endpoint — `DEBUG=True` swaps Redis for `DummyCache` + disables introspection guard

**Problem**: Local `DEBUG=True` replaces Redis cache with `DummyCache`; cache bugs not reproducible locally. Introspection disabled only when `DEBUG=False` (`docs/APPS.md` cross-cutting, `rosak/settings.py`).
**Root Cause**: Dev convenience swallowing cache layer.
**Fix**: _Not fixed — by design._ Documented trap; use `DummyCache`-aware test harness or run with `DEBUG=False` locally for cache repro.
**Prevention**: CI runs with prod-like cache; add integration test toggling `DEBUG` flag.

### [2026-08-24] rosak: `common/tasks.py` circular import hazard

**Problem**: `common/tasks.py` imports `spotting` and `incident` at module top level while both apps import `common` — genuine cycle; reason most other imports in that file are function-local (`docs/APPS.md:128`, `docs/components/common.md:60`).
**Root Cause**: Task needs cross-app models but sits in `common`.
**Fix**: _Not fixed._ Lazify imports or move task ownership to leaf apps; `tach.yml` already documents allowed edges.
**Prevention**: Enforce `tach check` in CI; prefer lazy string refs and function-local imports for cross-app models.

---

### Sources

- `docs/APPS.md` — Known Defects & Traps table (19 entries, 5 FIXED 2026-08-24) and Beat schedule / Dependency graph sections.
- `docs/components/operation.md` — DataLoader rough edges, `StationLine` ordinal, write-API stub defects.
- `docs/components/common.md` — Imgur hot path, admin mixin, `RETRY_ELAPSED`, cache and flag coupling.
- `docs/components/spotting.md` — `eventsCount`, `CheckConstraint`, `LocationEvent` FK, deletion policy, digest date.
- `docs/components/incident.md` — Dual join tables, `UniqueConstraint`, filter asserts, N+1 batching.
- `docs/components/chartography.md` — Through-table admin, hardcoded PK map, `force` dead param.
- `docs/components/reporting.md` — Missing enums, filter field name, vote constraints.
- `docs/components/generic.md` — `GeometricForm` Meta mutation, `GeoMultiPoint` copy-paste, `WebLocationInput` UNSET.
- `docs/components/telegram_provider.md` — Provenance chat filter, unbounded retry, blocked event loop.
- Git history: `1e2a421` (2026-08-24, 3 fixes), `bb1e519` (2026-08-19, DateGroupings), `c318fd4` (2026-08-18, GeoMultiPoint), `2af0092` (2026-08-24, docs cataloguing).

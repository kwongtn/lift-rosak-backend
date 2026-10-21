# Component: incident

## 📌 Purpose & Scope

- **Core Responsibility:** Owns the rail disruption record in two independent tiers, with no FK between them:
  - **Asset ledger:** `VehicleIncident` and `StationIncident`. Dated, ordered events per vehicle or station. `is_last` marks the current state.
  - **Calendar incident:** `CalendarIncident`, a service disruption over a datetime range, with lines, stations and vehicles, a chronology of `CalendarIncidentChronology` updates, markdown details, media and an `impact_factor`.
- It also owns the crowd-sourced feed: `SocialMediaLink` (canonical-URL dedup, votes, reply trees), `LineStatusReport` passenger-load reports that consolidate into a per-line pulse for `operation.Line`, and automated ingestion of official X posts.
- It owns web push too: `PushSubscription` stores one browser's FCM token and the lines it follows, and a MAJOR incident that goes LIVE through approval is pushed to those lines' subscribers (`services/push.py`).
- **Domain/Layer:** Django persistence and business logic (GIS via `PointField`), exposed as a read/write Strawberry GraphQL API. The only HTTP route is the X Activity API webhook (`incident/views.py`, registered in `rosak/urls.py`). There is no `incident/urls.py` and no signals. Writes come from GraphQL mutations, the `/upload/` → `common` media pipeline, the webhook, and `incident/tasks.py`.

## 🔌 Interface & Data Flow

### Inputs: GraphQL queries

Root fields come from `IncidentScalars` (`incident/schema/schema.py`): `vehicleIncidents`, `stationIncidents`, `calendarIncidents`, `calendarIncidentsBySeverityCount`, `pendingCalendarIncidents` (admin queue), `socialMediaLinks` (admin queue), `publicSocialMediaLinks` (cursor connection), `calendarIncidentCategories`, `calendarIncidentHistory` (logged in), `lineStatusHistory`, `networkStatusHistory`, `linesStatusHistory`, `lineStatusWeekProfile`, `lineStatusReports`, `pushSubscription` (logged in).

| Filter (`incident/schema/filters.py`) | Inputs |
| --- | --- |
| `IncidentAbstractFilter` | Undecorated mixin: `id`, `date`, `severity`, `is_last` |
| `VehicleIncidentFilter` / `StationIncidentFilter` | Mixin plus nested `vehicle` / `station` filter (from `operation.schema.filters`) |
| `CalendarIncidentFilter` | `id`, `severity`, `status: CalendarIncidentStatus`, `ongoing`, `activeNow`, `upcomingWithinDays`, `lines: LineFilter`, `stations: StationFilter`, `date: CalendarIncidentDateFilter` |

- **Calendar date filter.** `range` and `exact` use inclusive **interval overlap**: start ≤ window end AND (end ≥ window start OR open-ended). An open-ended incident must still start by the window end. Use `OR: {ongoing: true}` to keep the pinned "still broken" section regardless of the viewed month. Windows over 60 days raise `GraphQLError`. `month.exact` and `year.exact` are legacy calendar-part filters. The `month` branch has a known off-by-one (`month__lte = value + 1`, which assumes a 0-indexed JS month). MISTAKES.md 2026-08-24.
- **`ongoing`** maps to `end_datetime__isnull` and knows nothing about the start. Planned works with a known end never match `ongoing: true`, and an open-ended incident that has not started yet does. Use `activeNow` and `upcomingWithinDays` for those two questions.
- **`activeNow`** means in effect this instant: `start_datetime ≤ now AND (end_datetime IS NULL OR end_datetime ≥ now)`, both edges inclusive. `false` is the exact complement (`start_datetime > now OR end_datetime < now`). `now` is `timezone.now()`, which is naive local time here (`USE_TZ = False`).
- **`upcomingWithinDays: N`** means not started yet and starting within N days: `now < start_datetime ≤ now + N days`. An `N` outside 1 to 60 (`MAX_UPCOMING_DAYS`) raises `GraphQLError`. The lower edge is strict, so one incident never matches both `activeNow` and `upcomingWithinDays`.
- **`lines` / `stations`** take the nested `LineFilter` / `StationFilter` from `operation.schema.filters` and match an incident tagged with at least one matching row on `CalendarIncident.lines` / `.stations`. That is the join the admin edits, not `operation.Line.calendar_incidents`. Every input of those filters works, including `StationFilter.location` and `stationLine`, because `_tagged_with` runs the nested filter on the related model itself (so a `filter_field` there sees `Station`, not the incident), then matches `pk IN` the M2M table. A declarative nested filter would join instead, and a join repeats an incident once per matching row, so two matching lines would return it twice. An empty `lines: {}` is no filter, and `NOT: {lines: {...}}` keeps untagged incidents.
- **`status`** is an exact match on the `CalendarIncidentStatus` enum (`DRAFT`, `PENDING_APPROVAL`, `LIVE`, `REJECTED`, `PENDING_DELETION`). It is opt-in: `calendarIncidents` has no status gate, so without it every incident that is not soft-deleted comes back whatever its `status`, anonymous callers included. That covers `DRAFT` revisions of a `LIVE` incident (`parent_incident` set) and `REJECTED` rows. The insiden calendar relies on that and tags drafts, so a surface that must show only moderator-approved notices, such as the Rider board, sends `status: LIVE`. For several statuses, OR single ones: `{status: LIVE, OR: {status: DRAFT}}`.
- Every filter above is a plain `Q`. They AND with each other and with `date`, and they OR through the `OR: {...}` wrapper. A `null` value means no filter.
- `CalendarIncidentOrder`: `id`, `order`, `impact_factor`, `start_datetime`, `end_datetime`. Asset-level lists have no ordering input.
- `calendarIncidentsBySeverityCount(startDate, endDate, groupBy: GroupByEnum = DAY)`. `GroupByEnum` is `DAY | MONTH`. Both dates are required and inclusive, and **only `LIVE` incidents count**: drafts, pending-approval and rejected rows never do. Only non-empty buckets come back, oldest first. `MONTH` is a true per-month count (see Aggregation).
- `calendarIncidentHistory(id, limit = 50)`: latest first, `IsLoggedIn`.
- `pushSubscription(token: String!)`: `IsLoggedIn`. Returns the caller's own `PushSubscriptionScalar` for that token, so a device can restore its bell state. It returns null when the token is unknown **or registered by another account**, because holding a token does not prove you own someone else's subscription.

**`publicSocialMediaLinks`** (`get_public_social_media_links`, `incident/schema/resolvers.py`). Ordered `occurred_at DESC, id DESC`. The keyset cursor is the `(occurred_at, id)` pair.

| Argument | Default | Meaning |
| --- | --- | --- |
| `incidentId`, `lineId` | null | Scope |
| `first` / `after` | 20 / null | Page size and opaque cursor. Fetches `first + 1` to compute `hasNextPage`. |
| `mine` | null | The caller's own links, including `HIDDEN` ones. Never collapsed. Ignores `collapseThreads`. |
| `status: SocialMediaLinkStatus` | null | Narrows to one status. `status: HIDDEN` returns an empty page, not the hidden rows. |
| `currentServiceDayOnly` | false | `occurred_at ≥` the 03:00 service-day start (`services/line_status.py::service_day_start`). |
| `lastWeekOnly` | false | Half-open `[local midnight six days ago, local midnight today)` (`last_week_start`, `_event_window_before`). Deliberately calendar midnight, not the 03:00 rollover. |
| `displayTodayInLastWeek` | false | Drops the upper bound, so the window becomes the inclusive seven days. Inert unless `lastWeekOnly`. Combined with `currentServiceDayOnly` it is an intersection, empty from 03:00 until midnight. |
| `alignPageToDay` | false | Never ends a page mid-day. If the lookahead row shares the last row's local day, append that whole day. The page may exceed `first`, with no cap. |
| `collapseThreads` | false | Narrows to roots (`parent IS NULL`) before the count and the cursor. Each root carries its subtree (`sublinks`, `sublinkCount`). |

`totalCount` is the full filtered size, independent of cursor and `alignPageToDay`. It comes from a separate `acount()`. Moderation gates (automated-pending and `HIDDEN` exclusions) are described under Internal State.

**`socialMediaLinks`** (console queue) takes `search`, `categoryId`, `completed`, `hidden` (tri-state), `lineId`, `vehicleId`, `stationId`, `occurredAfter`, `occurredBefore`. It is ordered `-occurred_at, -id`, with inclusive windows on the same column the sort uses. ⚠️ `occurredAfter` / `occurredBefore` are a deliberate **breaking rename** of `createdAfter` / `createdBefore`. The old names are not aliased, so a stale client gets an "Unknown argument" error instead of a silent filter on the wrong column.

### Inputs: mutations

`IncidentMutations` composes six mixins from `incident/schema/mutations/`:

| Mixin | Mutations | Permission |
| --- | --- | --- |
| `IncidentCrudMutations` (`incidents.py`) | `createCalendarIncident`, `updateCalendarIncident`, `submitCalendarIncident`, `deleteCalendarIncident` | `IsLoggedIn` |
| | `approveCalendarIncident`, `rejectCalendarIncident` | `IsAdmin` |
| `ChronologyMutations` (`chronologies.py`) | `createChronology`, `updateChronology`, `reorderChronology`, `deleteChronology`, `requestChronologyDeletion` | `IsLoggedIn` |
| | `approveChronology`, `approveChronologyDeletion`, `rejectChronologyDeletion` | `IsAdmin` |
| `VoteMutations` (`interactions.py`) | `upvote`, `downvote`, `removeVote`, `upvoteChronology`, `downvoteChronology`, `removeChronologyVote` | `IsLoggedIn` |
| `SocialMediaLinkMutations` (`interactions.py`) | `submitSocialMediaLink`, `updateSocialMediaLink`, `deleteSocialMediaLink` | `IsLoggedIn` |
| | `groupSocialMediaLinks`, `ungroupSocialMediaLinks`, `reorderSocialMediaLinks` | `IsLoggedIn` plus the service ownership rule |
| | `submitFeedLink`, `submitLineStatusReport`, `upvoteSocialMediaLink`, `downvoteSocialMediaLink`, `removeSocialMediaLinkVote` | `IsLoggedIn` |
| | `markSocialMediaLinkCompleted` | `IsAdmin` |
| `ExtractionMutations` (`interactions.py`) | `extractDataFromUrl` | `IsLoggedIn` |
| `PushMutations` (`push.py`) | `registerPushToken`, `unregisterPushToken` | `IsLoggedIn` |

- 🔴 **The nine vote mutations return `VoteMutationPayload`, not `GenericMutationReturn`.** They return `ok`, `userVote`, `voteScore`, `upvotes` and `downvotes`, all from one aggregate round-trip (`services/votes.py::VoteOutcome`). `_vote_payload` in `interactions.py` is the only conversion point. Why: an `ok`-only response made clients project the new score themselves, and that projection raced the echo and other voters, so the indicator visibly snapped back. `ok` is kept, so `{ ok }` selections still work. The retype is still breaking by graphql-core's definition, so it is pinned in `EXPECTED_ACCEPTED_BREAKING_CHANGES` (`rosak/tests/test_schema_snapshot.py`).
- `submitFeedLink(input: FeedLinkInput)` returns `FeedLinkPayload` (`ok`, `link`, `isDuplicate`, `duplicateOfId`, `userVote`). Any logged-in user gets `LIVE`. The canonical URL is deduped, and a duplicate auto-upvotes the existing row without touching its `occurred_at`.
- `submitLineStatusReport(input)` returns `GenericMutationReturn` and creates one standalone `LineStatusReport`.
- `registerPushToken(token: String!, lineIds: [ID!]!)` returns `GenericMutationReturn` (`ok` only). It **upserts by token and replaces the lines**: send the full set every time, and `[]` keeps the row with no lines. A token already registered by another account is **re-owned** by the caller, because the browser holding it now belongs to the caller. The token is trimmed and must be 1 to 2048 ASCII characters. The cap is not FCM's: the unique btree index on `token` refuses a row over 2704 bytes with a raw `OperationalError`. A non-numeric or unknown line id is a validation error, and nothing is written. An id past the bigint range counts as unknown. `lineIds` holds at most 100 distinct ids (`MAX_LINE_IDS`). Each account keeps at most 20 tokens (`MAX_TOKENS_PER_USER`): registering past that deletes the account's least recently registered tokens (by `modified`), so a browser keeps its row by re-registering.
- `unregisterPushToken(token: String!)` deletes the caller's own row for that token. Another account's row is untouched, and an absent token still returns `ok: true`.
- **`updateSocialMediaLink` is replace-not-patch.** The service assigns `url` and `title` unconditionally and calls `.set()` on all four tag M2Ms. Every caller must resend the full payload, including `occurredAt`, where explicit `null` means "reset to the submission time". Admin edits land `LIVE`. A submitter's edit is forced back to `PENDING_APPROVAL`. Admins may set `HIDDEN`.
- `groupSocialMediaLinks(linkIds, parentId: ID = null)`, `ungroupSocialMediaLinks(linkIds)` and `reorderSocialMediaLinks(linkIds, parentId: Maybe<ID>)` are id-only, so grouping never travels through `SocialMediaLinkInput`. `group` returns the root of the affected conversation in `id`. `parentId` is an un-aliased rename of the old `threadId`. A stale client gets "Unknown argument/field". Pinned by `EXPECTED_ACCEPTED_BREAKING_CHANGES`. See the link tree section.

**Service-level permission matrix** (the GraphQL `IsLoggedIn` gate is only the floor):

| Operation | Non-admin | Admin |
| --- | --- | --- |
| Edit a LIVE incident | Creates a DRAFT revision (`parent_incident`). One open draft per incident; a second actor's draft is rejected with the spec message. OCC `expected_version` applies on every path. | In place |
| Edit DRAFT or own PENDING_APPROVAL | In place (author) | In place |
| Delete incident | Author, only when DRAFT or PENDING_APPROVAL | Any |
| Delete chronology | Author, when the chronology or its parent is DRAFT or PENDING_APPROVAL | Any |
| Request chronology deletion | Author or admin, LIVE chronologies only → `PENDING_DELETION` | n/a |
| Approve or reject chronology deletion | n/a | Soft-deletes, or reverts to LIVE |

- **Signals:** none. The audit trail is `django-simple-history` (`HistoricalRecords(cascade_delete_history=False)` on `CalendarIncident` and `CalendarIncidentChronology`) plus `TimeStampedModel`.

### Inputs: HTTP

- **`GET` / `POST /webhooks/x-api`** (name `x_api_webhook`, `incident/views.py`), registered in `rosak/urls.py` under `apps.is_installed("incident")`. It is `csrf_exempt` because X sends no CSRF token. The request is authenticated by X's HMAC over the raw body, not by a session. Behaviour is in Internal State.

### Outputs (GraphQL types, `incident/schema/scalars.py`)

- **`IncidentAbstractScalar`**: `id`, `date`, `severity`, `order`, `title`, `brief`, `is_last`. The `location` field is commented out, so the captured GIS point is never exposed. `VehicleIncident` and `StationIncident` add `vehicle` / `station`. Their `medias` field is also commented out.
- **`CalendarIncidentScalar`**: datetime range, `severity`, `status`, `title`, `brief`, `details`, `impact_factor: float`, `version` (OCC), `long_term`, `inaccurate`, `user` (creator), `lines`, `vehicles`, `stations`, `categories`, `chronologies`, plus resolved fields:
  - `medias` through `medias_from_calendar_incident_loader`.
  - `vote_score`, `vote_breakdown`, `user_vote`, batched through the vote loaders (generic `common.Vote` via ContentType).
  - `links(first = 10, after)` returns a `SocialMediaLinkConnection`, newest occurrence first (`occurred_at DESC, id DESC`). Page one comes from the `incident_links` loader. Continuation pages query directly, because per-parent cursors cannot be batched. The cursor format matches the root resolver, so a nested cursor can continue on the root query.
  - `has_details` (`@sync_to_async` emptiness check).
  - `last_updated` (`@sync_to_async`). It re-fetches the row, then runs a count and an ordered slice on `chronologies`, which is three extra queries per node. Invisible to `DjangoOptimizerExtension`, so it is the app's main N+1 hotspot.
- **`CalendarIncidentChronologyScalar`**: `id`, `order`, `status` (independent of the parent), `indicator`, `datetime`, `content`, `source_url`, a back-reference to the incident, and the three vote fields.
- **`CalendarIncidentHistoryEntryScalar`**: one diffed `django-simple-history` record. `timestamp` (UTC), `actor` (null for system), `change_type` (`created` / `updated` / `deleted`), `changed_fields` (from `diff_against`, internal history fields excluded).
- **`SocialMediaLinkScalar`**: `id`, `url`, `normalizedUrl` (computed on save), `title`, `description`, `status`, `created` (submission time, the moderation provenance), `occurredAt: DateTime!` (non-null, naive local), `completed`, `completedAt`, `isAutomated: Boolean!` (the "Official" badge), `completedBy` (nickname, or `firebase_id[:8]`), `user`, `categories`, `lines`, `vehicles`, `stations`, the tree fields `parentId`, `isThreadRoot`, `position`, `sublinkCount`, `sublinks` (recursive), and `voteScore` / `userVote`. Ingestion columns (`posted_at`, `post_id`, `raw_payload`, `socmed_account`) are deliberately not exposed. `SocialMediaLinkConnection` adds `totalCount`. `FeedLinkPayload` is the `submitFeedLink` return type.
- **`LineStatusReportScalar`**: `id`, `status` (`PassengerStatus`), `delayMinutes`, `notes`, `created`, `user`, `stations`. Served by `lineStatusReports(lineId, first, after)`.
- **`LineStatusHourBucket`** (`hourStart`, `hourEnd`, `count`, `dominantStatus`, `statusCounts: [PassengerStatusCount!]!`) and **`LineStatusHistory`** (line id plus buckets). **`LineStatusWeekBucket`** (`weekday`, `hour`, `count`, `dominantStatus`, `statusCounts`) is one weekday-hour slot of a typical week. See the service-day and typical-week sections.
- **`PushSubscriptionScalar`**: `token`, `lines` (operation `Line`). Served only by `pushSubscription`, only to the token's owner.
- **`CalendarIncidentGroupByDateSeverityScalar`**: `severity`, `date` (the first of the month in `MONTH` mode), `count`, `is_long_term` (null in `MONTH` mode). A flat row for calendar heat maps and monthly bars.

### Celery tasks (`incident/tasks.py`, schedule in `rosak/celery.py`)

| Task | Schedule | Notes |
| --- | --- | --- |
| `purge_soft_deleted_incidents` | 03:00 daily | Hard-deletes safedelete rows older than `SOFT_DELETED_RETENTION` (90 days). |
| `purge_rejected_incidents` | 03:30 daily | Hard-deletes `REJECTED` rows unchanged for `REJECTED_RETENTION` (30 days). |
| `ingest_official_posts` | every 5 min, `expires=240`, `time_limit=180` | Polls enabled X `SocMedAccount` rows. Registered only when `OFFICIAL_POST_POLLING_ENABLED` is set. Ships inert: returns `{"skipped": "disabled" \| "polling_disabled" \| "no_token"}` unless the master switch, the polling flag and `X_API_BEARER_TOKEN` are all set. `expires` sits under the period so a wedged run is never re-dispatched on top of itself. Never retries or sleeps. A per-handle `OfficialPostFetchError` is logged and the other handles still run. |
| `notify_official_post_links(link_ids)` | Off-beat | Dispatched by the webhook view, see Internal State. |
| `notify_push_subscribers(incident_id)` | Off-beat | Enqueued on commit by `approve_incident`, see Web push. `autoretry_for=FirebaseError` (raised by the FCM client, or by the service for a chunk that delivered nothing and saw a transient error), `max_retries=3`, `retry_backoff` capped at 600 s. Returns the number of messages FCM accepted. |

Beat `crontab` times are Malaysian local time. `CELERY_TIMEZONE` is set only inside `if USE_TZ:` (`rosak/settings.py`) and `USE_TZ` is `False`, so Celery falls back to Django's `TIME_ZONE` (`Asia/Kuala_Lumpur`, verified in the running `app` container). The service-day cutoffs in this app (`DAY_START_HOUR`, `service_day_start`) are a separate, local-time concept.

- **Telegram notification** (`_notify_created_links`, `_notify_new_link`, `_build_notification_text`). One message goes to `TELEGRAM_ADMIN_CHAT_ID` for each entry in `IngestSummary.created_ids`. The pass is skipped when that setting is blank. Re-scrapes announce nothing, because a duplicate has no id. The body holds the handle, the post's own time, the verbatim `description`, the permalink, and a `{FRONTEND_BASE_URL}/console/insiden/links` link to **review** (the row is already `LIVE`). Every dynamic value is `html.escape`d, and `raw_payload` is never rendered. Truncation keeps the escaped text under Telegram's 4096-character limit. The send goes through `telegram_provider.utils.send_message(..., return_log=True)`. The returned log is joined to the row by `TelegramSocialMediaLinkLog`, which is what lets a reply-`/approve` resolve. Failures are contained per link (warn and continue). The per-handle `notified` counter is reported in the result dict and not in `INGEST_COUNTERS`.

### Management commands (`incident/management/commands/`)

- **`ingest_official_posts`**: a manual backfill of the same path. `--handle` (repeatable), `--since` / `--until` (whole UTC days; these exclude the `since_id` fast path), `--limit`, `--fixture PATH` (offline, rejected with a date window), `--dry-run`. Failures become `CommandError`. A multi-handle run taken from settings is rejected as ambiguous unless `--handle` is given.
- **`export_official_posts`**: the read side. Exports every `is_automated=True` row as JSONL or CSV. Flags: `--handle` (`@` tolerated), `--since` / `--until` (inclusive UTC days over `posted_at`), `--format jsonl|csv`, `--output PATH|-`, `--include-raw`, `--dry-run`, `--push-to-hub REPO_ID`. Columns are the HuggingFace dataset schema in fixed order: `post_id`, `posted_at`, `handle`, `text` (verbatim `description`), `permalink`, plus `raw_payload` with `--include-raw`. Output is byte-stable. `--output -` sends the summary to stderr.
- **`x_webhook`**: operator lever for the webhook lifecycle. Subcommands: `register URL` (POST `/2/webhooks`), `list`, `delete ID`, `revalidate ID` (PUT, re-triggers CRC) and `subscribe HANDLE...` (one `post.create` subscription per handle, `@` stripped). `--webhook-id` is optional for `subscribe`. When omitted, there must be **exactly one** registered webhook, because guessing would attach subscriptions to the wrong endpoint silently. Authorised by `X_API_BEARER_TOKEN`, which must be **App-only**. The token is used only in an `Authorization` header and is never printed. Only `CrcValidationFailed` / `UrlValidationFailed` titles from the API are quoted in errors.

### Dependencies

- **Outbound.** `operation.Vehicle` and `operation.Station` (FK, CASCADE). `operation.Line`, `Station` and `Vehicle` (M2M from `CalendarIncident`). `operation.Line` (FK, PROTECT) and `Station` (M2M) from `LineStatusReport`. `operation.Line` (M2M) from `PushSubscription`. `common.Media` (M2M on the three incident models, through `CalendarIncidentMedia` for the calendar tier). `common.User` (`created_by`, and `user` on `SocialMediaLink`, `LineStatusReport` and `PushSubscription`). `common.Vote` (generic, via ContentType, including `SocialMediaLink`). `generic.views.GeometricForm`. `operation.schema.filters` and `scalars` in GraphQL. `telegram_provider.utils.send_message` and `TelegramSocialMediaLinkLog` at module level in `incident/tasks.py`. That is the one-way `incident → telegram_provider` edge.
- **Inbound.**
  - `operation/admin.py` imports `VehicleIncidentInlineAdmin` and `StationIncidentInlineAdmin`. The asset ledger is edited from operation admin pages.
  - `operation/schema/loaders.py` imports `VehicleIncident` for `incident_from_vehicle_loader` and `incident_count_from_vehicle_loader`, which back `Vehicle.incidents`, `incidentCount` and `canExpand`. No station equivalent exists (Feature 5).
  - `common/views.py` (`GenericUpload` stashes `calendar_incident_id` in metadata), `common/tasks.py` (creates the `CalendarIncidentMedia` row after upload; `cleanup_temporary_media_task` targets this app), and `common/enums.py`.
  - `telegram_provider` references `incident` only through the `TelegramSocialMediaLinkLog` FK (migration `0005`) and the `/approve` handler.
- **Firebase Cloud Messaging.** `services/push.py` sends through `firebase_admin.messaging`. The default app is initialised once in `spotting/apps.py` (`initialize_app()`), so the Celery worker needs the same `GOOGLE_APPLICATION_CREDENTIALS` as the API.
- **Third-party.** `model_utils.TimeStampedModel`, `ordered_model`, `mdeditor` (`details`), `pendulum` (bucketing), `django.contrib.gis`, `django-safedelete==1.5.0`, `django-simple-history`, `django-choices-field` (`TextChoicesField`), and `django-tree-queries==0.26.1` (`OrderableTreeNode`, `TreeNodeForeignKey`). The last requires `"tree_queries"` in `INSTALLED_APPS`, or it raises `tree_queries.E001`. It was chosen over `django-treenode` because `tree_path` is a per-query CTE annotation. Nothing is stored, there is no in-process tree, and no signal runs on every `save()`. That matters on a high-write table served by granian, the celery worker and beat.

## ⚙️ Internal State & Logic

### Enums (`incident/enums.py`)

Stored as `TextChoicesField`, or as `CharField(choices=…)` for the legacy severity fields.

| Enum | Values | Applies to |
| --- | --- | --- |
| `IncidentSeverity` | `CRITICAL`, `TRIVIA`, `STATUS` | Asset tier. Mixes true severity with a "status annotation" bucket. |
| `CalendarIncidentSeverity` | `MAJOR` (line-wide), `MINOR` (single vehicle), `OTHERS` | Calendar tier |
| `CalendarIncidentChronologyIndicator` | `GREEN`, `RED`, `BLUE`, `GRAY` | Timeline dot colour |
| `CalendarIncidentStatus` | `DRAFT`, `PENDING_APPROVAL`, `LIVE`, `REJECTED`, `PENDING_DELETION` | Incident and chronology status. `PENDING_DELETION` is set only on chronologies. |
| `SocialMediaLinkStatus` | `LIVE`, `PENDING_APPROVAL`, `HIDDEN` | Link lifecycle. Deliberately not the incident enum. `HIDDEN` is a moderation decision, not a lifecycle stage. |
| `IngestPlatform` | `X` | Source platform. One member by design. A second platform is a new member plus its own fetch function. |
| `PassengerStatus` | `NORMAL`, `BUSY`, `CROWDED`, `EXTREMELY_CROWDED`, `BACKLOGGED`, `DELAYED`, `DISRUPTED` | Crowd-reported load. Declaration order is the consolidation severity rank. |

The two severity vocabularies are not interchangeable, and there is no mapping between them.

### Asset tier vs calendar tier (`models.py`)

- `IncidentAbstractModel` (`TimeStampedModel` + `OrderedModel`) holds `date` (a `DateField`, day granularity), `severity`, optional `location: PointField`, `title`, `brief`, `is_last` and an editable `order`. `order` is still marked `# Remove after beta`.
- `VehicleIncident` and `StationIncident` set `order_with_respect_to` to their parent, so each asset has its own ordered history. Each has a unique constraint with `condition=Q(is_last=True)`, so there is at most one current row per asset.
- `CalendarIncident` models a **span**: `start_datetime`, nullable `end_datetime` (null means ongoing), `long_term` (collapse to the start date in month view), `inaccurate` (show an "unverified" badge), `impact_factor` (`Decimal(5,2)`), `brief`, markdown `details`, M2Ms, `status`, `version` (OCC counter) and a nullable `parent_incident` FK for draft revisions.
- Its narrative lives in `CalendarIncidentChronology` (`related_name="chronologies"`, ordered per incident), with its own `status`.
- **No FK between the tiers.** A vehicle ledger row cannot point at its calendar incident. Correlation is only implicit, through shared asset and date.

### Feed links and the passenger pulse (`services/feed_links.py`, `services/line_status.py`, `services/urls.py`)

- **Dedup.** `normalized_url` is recomputed on every `save()` by `canonicalize_url`, which strips `TRACKING_PARAMS` (`fbclid`, `gclid`, `igshid`, `si`, `utm_*`), lowercases the host, and drops the fragment and trailing slash. Dedup happens in `submit_feed_link` (a global canonical match auto-upvotes the existing row, otherwise the row is created `LIVE`). It is **not** a DB constraint.
- **Ingestion columns.** `socmed_account` (nullable FK), `post_id`, `posted_at`, `is_automated` and `raw_payload` are null or default for community links.
- **`LineStatusReport`** holds `status`, optional `delay_minutes`, `notes`, `stations` and `link`. `consolidate` takes the last `WINDOW_MINUTES = 15` minutes of reports and picks one `PassengerStatus` by weighted majority. A linked report weighs `1 + max(net_vote, 0)`, an unlinked one weighs `1`. Ties break by recency, then by enum rank. The full per-status count dict is returned alongside.
- **Pulse on `operation.Line`.** `load_line_pulses` batches per line in three flat queries, feeding the `passengerStatus`, `passengerStatusMessage` and `pulseLinks` fields. `pulseLinks` is capped at `_MAX_PULSE_LINKS = 5`.
- `fetch_page_title` is a best-effort `httpx` `<title>` scrape. Every failure returns `""`.

### Service-day history (`services/line_status.py`)

`lineStatusHistory`, `networkStatusHistory` and `linesStatusHistory` are three views of one read. `_service_day_entries(line_ids, day_start_hour=, days_ago=, now=)` validates `dayStartHour` and `daysAgo`, computes the service-day start (`service_day_start`, moved back `days_ago` days) and issues **one** `LineStatusReport` query. `line_ids=None` means every line. An empty sequence returns before any query, so `linesStatusHistory(lineIds: [])` is zero-query. All three bucket through `bucket_hourly`, and `_hour_bucket()` in `schema/resolvers.py` is the single place that holds the status mapping and the `statusCounts` ordering (through `_dominant_status_enum` and `_status_count_rows`, which the typical-week query shares).

| Query | Scope | With data | Without data |
| --- | --- | --- | --- |
| `lineStatusHistory(lineId, dayStartHour = 3, daysAgo = 0)` | One line | 24 buckets (03:00 → 02:00, empty hours zero-filled) | `[]`. The client's "No data" state. |
| `networkStatusHistory(dayStartHour = 3, daysAgo = 0)` | All lines, one grouped read | 24 buckets | `[]` |
| `linesStatusHistory(lineIds, dayStartHour = 3, daysAgo = 0)` | N lines, one query | One entry per requested id, each with 24 buckets | The same entries, each with `buckets: []` |

- **`daysAgo`** (0 to 56, default 0, and `null` reads as 0) picks the service day: `N` is the one that started N service days before the current one, so it counts service days, not calendar days (at 01:00 the current service day is still yesterday's). A past day is read whole, `[day_start, day_start + 24h)`, never cut off at now, and bucketed exactly like today. Its end is exclusive: a report stamped at the next service day's first instant belongs to that day, and cannot turn an empty day into 24 empty buckets (`created__lt` in the read, and the same cap in `bucket_hourly`). An out-of-range value raises `LineStatusValidationError`, like `dayStartHour`, even for an empty `lineIds`. Clients send a literal integer and the backend does all the date arithmetic, so a client's query variables stay free of clock-derived values.
- `statusCounts` lists the per-status tally in enum order, zeros omitted. It sums to `count`, and it is `[]` for an empty hour.
- `networkStatusHistory` is a **network aggregate**. An hour's tally covers every line, so it answers "how is the network doing". Drawing it as one line's series would attribute other lines' reports to that line.
- `linesStatusHistory` returns one entry per requested id, in request order. The entry existing does not mean the line reported anything. Duplicate ids collapse to the first occurrence. `lineIds` is capped at `MAX_LINES_PER_HISTORY_REQUEST = 64` (`LineStatusValidationError`, surfaced as `GraphQLError`). The cap is not a query-count guard.
- `lineId` (and every entry of `lineIds`) must be numeric. Anything else is a validation error (`GraphQLError`), not a raw `ValueError`.
- All three are public (no permission classes).
- ⚠️ The network read filters on `created` alone. The index is `(line, created)` (migration `0026`, `incident_li_line_id_828375_idx`), so the read is a sequential scan of the service day's rows (a past day, `daysAgo > 0`, costs the same). That is the right trade at current volume. If the report table grows by orders of magnitude, add a `created`-leading index first. Do not split the read.

### Typical week (`services/line_status.py`)

`lineStatusWeekProfile(lineId: ID!, weeks: Int = 6, dayStartHour: Int = 3): [LineStatusWeekBucket!]!` answers "is this line usually bad, and when?". `load_line_status_week_profile` issues **one** `LineStatusReport` query for the line over the rolling window `[now - weeks * 7 days, now]` (it hits the `(line, created)` index and reads only `status` and `created`), and the pure `bucket_week_profile(entries, now=, weeks=, day_start_hour=)` tallies the rows per (weekday, hour), the way `bucket_hourly` does per hour.

- **Shape.** `[]` when the line has no report in the window (the "no data" state), otherwise **all 168 slots**: empty ones carry `count: 0`, `dominantStatus: null` and `statusCounts: []`. Slots run Monday first and, within a weekday, in service-day hour order (`dayStartHour` through 23, then 0 up to `dayStartHour - 1`), so a client can lay a weekday out with the same columns as the daily history chart.
- **`weekday`** is 0 = Monday to 6 = Sunday of the **service** day the report belongs to, and **`hour`** is the local clock hour 0 to 23. Stored times are naive local time (`USE_TZ = False`, `Asia/Kuala_Lumpur`), so the stored clock is read as it is (a test pins `USE_TZ` off, because turning it on would shift every slot). The report is shifted back by `dayStartHour` before its weekday is read: with the default 03:00 start a 01:30 Tuesday report counts toward Monday at hour 1, exactly where the hourly chart files it, and `dayStartHour: 0` gives plain calendar weekdays.
- **`count` is a raw total over the window's weeks**, not an average, so a client that wants a minimum-report threshold ("not enough reports") applies its own to `count`. The window is rolling and not aligned to service days, so it includes the current day so far.
- **`dominantStatus` and `statusCounts`** follow the hourly-bucket rules by sharing their code: `_dominant_status` (most frequent, ties to the most severe) and `_status_count_rows` (enum order, zeros omitted, summing to `count`).
- `weeks` must be 1 to 12 (`MAX_WEEK_PROFILE_WEEKS`; `null` reads as the default 6) and `dayStartHour` 0 to 23, else `LineStatusValidationError` (surfaced as `GraphQLError`). A non-numeric `lineId` is a `GraphQLError` too. The line is not checked for existence, so an unknown id answers `[]`. Public, like the other history queries.
- ⚠️ The tally runs in Python over every row of the window, up to 12 weeks of one line. That is the right trade at current volume. If per-line report volume grows by orders of magnitude, aggregate in the database instead (`Count` grouped by status, hour and the shifted weekday).

### X Activity API webhook (`incident/views.py`, `incident/services/x_webhooks.py`)

The primary ingestion path. The 5-minute poll is the fallback. It is a plain synchronous Django view, not DRF. There is no authentication, serializer or content negotiation, only an HMAC over the raw bytes and a fast 200. All crypto and DB work lives in the service. `views.py` only validates, delegates and acknowledges.

| Request | Response |
| --- | --- |
| `GET` | 200 `{"response_token": "sha256=…"}`. 400 when `crc_token` is missing. 503 when no signing secret is configured (operator-fixable, so X retries are pointless). |
| `POST` | 200 `{"status": "ok", "events", "ingested", "skipped", "unresolved"}`. 400 for non-JSON or a rejected payload. 403 for an absent or wrong signature. 503 for no secret or no system author. |
| Other | 405 with `Allow: GET, POST` |

Load-bearing choices:

- **Signature covers raw bytes.** `request.body` is read once and passed to `verify_webhook_signature(headers, raw_body)`. The parsed JSON is never re-serialised, because that breaks when X changes key order. Each `SIGNATURE_CANDIDATES` pair (`X-Twitter-Webhooks-Signature-OAuth2` with `X_API_OAUTH2_CLIENT_SECRET`, and the legacy `X-Twitter-Webhooks-Signature` with `X_API_SECRET_KEY`) is tried only when its secret is configured. An empty secret would accept a signature anyone can compute. Comparison is `hmac.compare_digest` over UTF-8 bytes.
- **CRC uses the preferred secret only.** `_preferred_signing_secret` returns `X_API_OAUTH2_CLIENT_SECRET` when set, since that is the secret X verifies the answer against. The legacy header is not tried for CRC.
- **Acknowledgement is the design constraint.** X retries any non-2xx and expects an answer within 10 seconds. So the DB write is inline (a handful of `get_or_create`s), and Telegram is handed to `notify_official_post_links`. A broker outage is logged and still answered 200, because the row is already committed and approvable from the console. `OfficialPostIngestError` (no system author) is the one 503, so X redelivers rather than the post being dropped silently.
- **Non-errors are acknowledged, not refused.** `OFFICIAL_POST_INGESTION_ENABLED=false` answers `{"status": "ignored", "reason": "ingestion disabled"}`. A non-`post.create` event (for example `post.delete`) answers 200 having done nothing.
- **Envelope.** `_expansion_containers` returns the containers an `includes` expansion may hang off, most-current first: `data` (where the Activity API puts `data.includes`) before a top-level `includes`. A stale top-level copy can never shadow the real one. Reading the wrong envelope drops every delivery silently (MISTAKES.md 2026-09-28).
- **Event seam.** `EVENT_POST_CREATE = "post.create"`. `_create_items` maps an envelope to items. Other event types are acknowledged and ignored. `WebhookIngestResult` enforces `ingested + skipped + unresolved == events`, so a redelivery that creates nothing shows as `ingested=0`, not as silence.

**Account attribution (`_resolve_account`).** Guessing is the one thing this path must never do. A permalink built from the wrong handle is a permanent public misattribution, while a dropped post is recovered by polling. Three rules, in order:

1. `data.includes.users[]`, matched on `payload.author_id`. This is the only attribution source that arrives inside the signed body, and it costs no network call. The matching object goes to `resolve_account(..., create=True)`, so an unknown author auto-registers under `Unassigned` with an empty `user_id`.
2. Otherwise, look up by `user_id` only (`author_id` or the filter's `user_id`) in `SocMedAccount`. `author_id` wins over `filter.user_id`, because a reply by another account carries the tracked account in the filter. On a miss, run `sync_account_profiles()` once and retry.
3. No match: counted as `unresolved`, warned and dropped.

Replies, quotes and reposts are all `post.create` and are all ingested, matching the poll's `exclude_retweets=False`. The deprecated AAA `tweet_create_events` shape is parsed defensively.

**Settings and troubleshooting.**

| Setting | Used for | If unset |
| --- | --- | --- |
| `X_API_OAUTH2_CLIENT_SECRET` | CRC answer and delivery verification (preferred). X verifies the CRC answer against this secret. Obtain it from the developer portal (the app's OAuth 2.0 client). | CRC falls back to `X_API_SECRET_KEY`, and only the legacy signature header is verified. |
| `X_API_SECRET_KEY` | Legacy OAuth 1.0 consumer secret, used for delivery verification | Sufficient alone for a POST-verified app. A CRC-only config needs the OAuth 2.0 secret, or a re-register against whichever secret is configured. |
| `X_API_BEARER_TOKEN` | `x_webhook` command | Registration and subscribe cannot run. The receiver needs no bearer. |
| `OFFICIAL_POST_INGESTION_ENABLED` | Actual writes | Every delivery is acknowledged `ignored`. Nothing is written, and X is not made to retry. |
| `OFFICIAL_POST_POLLING_ENABLED` | Polling only | Off by design. The webhook is primary. |
| `TELEGRAM_ADMIN_CHAT_ID` | Notifications | Rows still ingest. Nobody is told, and the log says so. |

If `CrcValidationFailed` appears on registration, check in order: (1) the endpoint is public HTTPS with **no port**, and X's fetcher does not follow redirects; (2) `GET ?crc_token=…` answers 200 within 10 seconds; (3) the configured secret is the one X signs with (prefer `X_API_OAUTH2_CLIENT_SECRET`), the most common cause; (4) the app was restarted after the secret changed, since values are read at import. `UrlValidationFailed` means the URL itself is unacceptable.

### Official-post ingestion (`services/official_posts.py`)

- **Source.** The `SocMedAccount` registry is the single source of truth. `OFFICIAL_POST_HANDLES` no longer exists. Posts land as `SocialMediaLink` rows authored by the `system:official-ingest` service user, which `get_system_author()` resolves. A missing user raises `OfficialPostIngestError`.
- **Bounded paging.** `fetch_user_posts` walks `next_token` backwards with a hard `_MAX_PAGES = 10` ceiling. The periodic task uses `since_id=latest_post_id(account)`, so a re-scrape cannot fan out into hundreds of requests.
- **Two failure vocabularies.** `OfficialPostFetchError` (transport, token, rate limit; message sanitised so a bearer token never reaches a log) is caught per handle and the tick continues. `OfficialPostIngestError` propagates, because a missing service user is a deployment fault.
- **Idempotency is structural.** A partial `UniqueConstraint` on `(socmed_account, post_id)` is the DB backstop. The service re-reads on `IntegrityError` rather than taking a lock. Pre-create existence checks mean a re-ingest never resurrects an admin-`HIDDEN` official row.
- **Auto-publish.** Created rows are `LIVE`. The operator's announcement is the only gate. `ingest_posts(posts, *, author, dry_run=False)` returns `IngestSummary(fetched, created, skipped, duplicate_urls, created_ids)`. `dry_run` counts would-be creations in the same code path and writes nothing. Unknown handles auto-register under `Unassigned` with no API call.
- **Offline source.** `load_fixture_posts(path, *, handle=None)` reads a JSON fixture. Fixtures under `incident/fixtures/` are what the test suite replays. `--fixture` with `--dry-run` gives a network-free import rehearsal.
- **Decode once.** `tweet_to_raw_post` is the single mapping into `RawPost`, shared by the poll, the fixture loader and the webhook parser. It runs `html.unescape` exactly once. `RawPost.text` becomes `SocialMediaLink.title` (truncated to `TITLE_MAX_LENGTH = 256` after decoding) and `description`. `RawPost.raw` stays as the provider sent it, so `raw_payload` keeps the encoded original for export fidelity. Never decode a second time, because `&amp;amp;` is an escaped entity and a second pass would store a bare `&`.

### Account registry (`models.py`: `Agency`, `SocMedAccount`)

- `SocMedAccount` is unique on `(platform, handle)` and on non-empty `(platform, user_id)`. An empty `user_id` means "not yet resolved", and many rows may share it.
- `is_enabled` (default `True`) gates the **polling task only**, which iterates enabled X accounts ordered by handle. The webhook is unaffected, because it resolves by the delivery's own author id.
- Every ingest path converges on `resolve_account(platform, *, handle, user_id, raw_payload, display_name, create)`. It looks up by `user_id` first, the strongest key, then by `handle`. A hit back-fills a missing `user_id` and refreshes the display name and payload when the caller holds the full user object. A miss with `create=True` and a known handle auto-registers under `Unassigned`. It never calls the API.
- The only live lookup is `ensure_user_profile(account)`, a `GET /2/users/by/username/{handle}` when `user_id` is empty. `sync_account_profiles()` is the bounded sweep over rows missing `user_id`. It catches per-account errors and continues. The webhook fallback and `x_webhook subscribe` both rely on it.
- Migration `0029` seeds the agencies (`Prasarana Malaysia Berhad`, `Unassigned`) and `askrapidkl` / `myrapidkl` with their full user payloads baked in, so staging and prod need no API call. It also moves `SocialMediaLink` onto the nullable `socmed_account` FK.

### Export properties (`management/commands/export_official_posts.py`)

- **Bounded memory.** Rows stream through `.only(...).iterator(chunk_size=500)`, a server-side cursor. `raw_payload` is selected only when exported. `--push-to-hub` is the one exception, because `Dataset.from_dict` needs the whole set.
- **Byte-stable output.** The sort key is `posted_at, post_id, id`. `id` is the tiebreak, because both leading keys are nullable and "same input → same output" needs a total order.
- **No new dependency, no leaked secret.** `datasets` is lazy-imported. `HF_TOKEN` comes from the environment and is never printed. `private=True` is unconditional, because redistributing tweet content on the Hub is outside X's terms.
- **Timezone.** The exported `posted_at` is the stored column verbatim. With `USE_TZ = False` that is naive local time. The instant is correct and the offset is missing. The `--since` / `--until` bounds stay aware, so the window is a true UTC day.

### Web push (`services/push.py`, `services/incidents.py::_enqueue_push`, `tasks.py`)

- **Trigger.** `approve_incident` calls `_enqueue_push` in two cases. A `PENDING_APPROVAL` row promoted to LIVE is enqueued whatever its severity, and the task decides. A revision merge is enqueued when it leaves the parent LIVE and MAJOR and the parent was not both before: newly LIVE (for example from `REJECTED`), or a LIVE MINOR parent escalated to MAJOR. A merge into a parent that was already LIVE and MAJOR is an edit and does not push, even when it adds lines. `transaction.on_commit(..., robust=True)` runs the `delay` after the merge's atomic block commits (at once in autocommit), and a broker outage is logged, never raised, because the approval already stands.
- **Not a trigger.** An admin's `createCalendarIncident` (born LIVE, never approved), an admin edit that raises a LIVE incident to MAJOR, Django admin edits, and official-post ingestion do not push.
- **Who gets it.** `notify_major_incident` sends nothing unless the incident exists, is not soft-deleted, is `LIVE` and is `MAJOR`. Recipients are the distinct tokens of subscriptions whose lines intersect `CalendarIncident.lines` (the admin-edited join). A device subscribed to several affected lines gets one message.
- **Cooldown.** At most one push per line per 30 minutes (`COOLDOWN_SECONDS`). Each affected line is claimed with `cache.add("push:line:<id>:cooldown", 1, timeout=1800)`, which is atomic, so two concurrent approvals on one line send once. A line in its cooldown is skipped, and the other lines of the same incident still push. Only affected lines that have subscribers are claimed, so a line nobody follows is not muted for someone who subscribes during the window. ⚠️ Local `DEBUG=True` uses `DummyCache`, whose `add` always succeeds, so the cooldown never limits locally. Test it with a `LocMemCache` override, as `incident/tests_push.py` does.
- **Message.** Title `"<line codes, by code>: <title>"` cut to 100 characters, body `brief` cut to 150, and `webpush.fcm_options.link` = `{FRONTEND_BASE_URL}/insiden/<start date YYYY-MM-DD>`. FCM rejects a link that is not `https://`, so `FRONTEND_BASE_URL` must be https wherever pushes are sent. Tokens go out in chunks of 500 through `messaging.send_each_for_multicast`.
- **Failures.** A token answered with `UnregisteredError` or `SenderIdMismatchError` is deleted. A token answered with `InvalidArgumentError` is deleted only when another message in its chunk was delivered: every message in a chunk carries one payload, so the token is at fault. With nothing delivered, the payload may be at fault, so nothing is deleted. Any other per-token failure is kept and logged once per incident as a count by error type. Tokens are never logged.
- **Retry.** ⚠️ `send_each_for_multicast` (firebase_admin 7.7) does not raise on an FCM outage. It returns the error per token (`UnavailableError` for a 503 or no connection, `InternalError`, `ResourceExhaustedError` / `QuotaExceededError`, `DeadlineExceededError`), and raises only `UnknownError` when its thread pool fails. So a chunk that delivered nothing and saw one of those `TRANSIENT_ERRORS` raises `UnavailableError` itself. Any raise releases this run's cooldown claims before it propagates, so the task's retry can send again. Transient failures beside a delivered message are only logged, not retried. A failure after an earlier chunk went out re-sends that chunk on retry (only above 500 recipients).

### Moderation gates (`schema/resolvers.py`, `services/social_link_visibility.py`)

The public feed applies two exclusions after the `status` narrowing and before `totalCount`, so the count and the page always agree:

1. **Automated-pending gate.** `exclude(is_automated=True, status=PENDING_APPROVAL)`. This is a safety net for legacy automated rows parked in the old approval state. Official ingestion writes `LIVE`, so the gate does not sit on the publish path. It is scoped to `is_automated` on purpose. Community links that are pending still show with their pending icon.
2. **`HIDDEN` gate.** `exclude(status=HIDDEN)`. `HIDDEN` is a moderation verdict, not a lifecycle stage, and it applies to community rows too. It defeats resurrection: `status: HIDDEN` returns an empty page with `totalCount: 0`. The `mine` branch is exempt, so an owner still sees their own hidden submission.

Other moderation rules:

- The console (`get_social_media_links`) lists all statuses by default, including `HIDDEN`, so an admin can find and un-hide a row. Its `hidden` tri-state narrows the set: omitted means all, `true` means only `HIDDEN`, `false` excludes it.
- Only admins can set `HIDDEN`. A non-admin edit is forced to `PENDING_APPROVAL`.
- Telegram `/approve` acts only on `PENDING_APPROVAL` rows. Anything else answers "Link is not awaiting approval."
- **Single source of truth.** `services/social_link_visibility.py::is_publicly_visible(link)` is the per-row predicate. The queryset `.exclude()` pair is its deliberate twin, because a per-row Python filter would not shrink `totalCount` or the page. The scalar applies the predicate in one place, `schema/scalars.py::_publicly_visible_subtree`. To change the rule, change the predicate first. Any new gate must call `is_publicly_visible`, not re-derive the `.exclude()`s.
- The moderation surface is the console at `{FRONTEND_BASE_URL}/console/insiden/links`, and Telegram `/approve` for any legacy row still pending.

### Event datetime: `SocialMediaLink.occurred_at` (`models.py`, `services/social_links.py`, `services/feed_links.py`, `services/official_posts.py`)

- `created` is when someone reported the link. It is the provenance column. `occurred_at` is when the thing happened. Every ordering, window, day header and keyset cursor is built on `occurred_at`. A post at 09:00 that was reported at 09:40 sorts and displays at 09:00.
- **NOT NULL, deliberately.** Keyset pagination needs a total order. A nullable column would force `Coalesce` into every filter and sort NULLs last on a DESC scan. Index `socialmedialink_occurred_idx` is `("-occurred_at", "-id")`. `id` is the tiebreak, because two posts can share a minute.
- **`posted_at` is read-only provider provenance.** Nothing may read-modify-write it. Export stays on `posted_at`, because an archive's purpose is provider fidelity. On the automated path both columns are written from `RawPost.posted_at` inside `ingest_posts`, the only automated writer.
- **Two different tri-states.** On update, `SocialMediaLinkWrite.occurred_at` is `UNSET` (leave alone), a datetime (set), or explicit `None` (reset to `link.created`, the escape hatch because the column cannot hold null). On submit, the kwarg is omitted so the model default fires. `FeedLinkInput.occurred_at` is a flat two-state `Maybe`, because that path only inserts. A duplicate canonical URL does not touch the existing row's `occurred_at`.
- **Timezone.** With `USE_TZ = False` and `TIME_ZONE = "Asia/Kuala_Lumpur"`, every stored datetime is naive local time. `occurredAt` serialises with no offset, and it must never be `make_aware`d or `astimezone`d. Migration `0030` backfills with a single SQL `Coalesce("posted_at", "created")`. A per-row Python loop would shift every row by +08:00 (MISTAKES.md 2026-09-26 and 2026-09-30).
- **Cursor.** Keyset tokens encode a timestamp and an id, but no column name. Changing a cursor's sort column needs a versioned encoding or a restart from page one (MISTAKES.md 2026-09-30).

### Link tree: `SocialMediaLink.parent` and `position` (`models.py`, `services/social_link_threads.py`, `services/social_link_visibility.py`)

A conversation is an **ordered nested tree**. `SocialMediaLink` inherits `tree_queries.OrderableTreeNode`. `parent` is a `TreeNodeForeignKey("self", null=True, related_name="children", on_delete=SET_NULL)`. The library supplies `position` (the sibling sequence) and `Meta.ordering = ["position"]`. A **root** is a row with `parent_id IS NULL`. `tree_path` is never stored, because it is a recursive-CTE annotation computed per query.

**Migration `0031`** is hand-ordered, and the order is load-bearing: `AddField(parent)`, `AddField(position)`, `AlterModelOptions`, then a reversible `RunPython` that folds any old `thread` groups into `parent` and backfills `position` (`RowNumber` × 10, partitioned by `parent_id`, ordered by `(occurred_at, id)`), then `RemoveField(thread)`. Both halves of the `RunPython` end with `SET CONSTRAINTS ALL IMMEDIATE`. The FKs are `DEFERRABLE INITIALLY DEFERRED`, so the re-parenting writes queue trigger events that block the following DDL with `ObjectInUse`. The reverse can rebuild `thread` from `parent` only because `RemoveField` is the last forward step. The dev database had no groups, so the conversion is defensive. It runs on every apply, not just the deploy it was written for (MISTAKES.md 2026-10-01).

**Five invariants, all enforced above the DB:**

- **No cycles, checked in `save()`.** The library's loop protection lives in `TreeNode.clean()`, which only `full_clean()` calls. A plain save of a cycle would be unreachable from every tree query. `SocialMediaLink.save()` runs `_guard_tree_cycle` first and raises `ValidationError`. It checks both spellings, `parent` and `parent_id`, in `update_fields`, because Django matches either. `bulk_create` and `bulk_update` bypass `save()`, so the service re-checks before any write.
- **Depth ≤ `MAX_THREAD_DEPTH = 3`.** A root is depth 0, so there are four levels. This is a write-side guard. The read side is not clamped, because clamping would invent rows. The bound applies to the resulting depth and counts the subtrees that travel with moved links.
- **`position` is assigned explicitly.** The library appends at `max(siblings) + 10` through a non-atomic read-then-write, never recomputes it on re-parent, and `bulk_create` skips it. `_reindex_siblings` renumbers the whole affected sibling set to `10, 20, 30, …` on every structural write.
- **Permissions are all-or-nothing.** An admin may group, ungroup and reorder any link. A submitter may do so only for their own links. The check covers the whole selection **and** the named target parent, and a rejected call writes nothing. The check is on the named link rather than the root. A submitter who owns a sublink can deepen a tree an admin created, which is an integrity question, not a confidentiality one. If submitters can nest under conversations they did not start, check the root too.
- **`on_delete=SET_NULL`** is the opposite of the library's hardcoded `CASCADE`. Deleting a link promotes its sublinks to roots instead of deleting a group nobody asked to delete. This works because the library finds the tree by the field **name** `parent` and never inspects `on_delete`. Renaming the field would break the tree. Pinned by `TreeDeletePromotionTests` (`tests/incident/test_social_link_tree_model.py`).

**Mutation semantics:**

| Mutation | Semantics |
| --- | --- |
| `groupSocialMediaLinks(linkIds, parentId: ID = null)` | **`parentId: null` starts a new conversation**. It does not make separate roots. The root is the selected link with the smallest `(occurred_at, id)`, and every other selected link becomes its direct child in that order. A `parentId` nests the selection as direct children of that link, whether it is a root or a sublink. The return `id` is the root of the affected conversation. |
| `ungroupSocialMediaLinks(linkIds)` | Clears `parent` on **exactly** the named links, which become roots. This is not a cascade. A link's own sublinks stay under it, so the branch continues under a representative that is now a root. A cascade would have to guess a new parent. Ungrouping does not renumber, so roots can tie on `position`. |
| `reorderSocialMediaLinks(linkIds, parentId: Maybe<ID>)` | A **permutation of one existing sibling set**, not a move. Every id must already be a child of `parentId` (`null` means the roots). Anything else is rejected with a message pointing at `groupSocialMediaLinks`. The named order becomes `10, 20, 30, …`, and unnamed siblings keep their relative order after them. |

- **Why `Maybe` only on reorder.** In `group`, omitted and explicit `null` both mean "elect a root", so a plain `ID = null` is honest. In `reorder` they are different requests. An explicit `null` reorders the roots. An omitted `parentId` names no sibling set and is rejected, since a plain nullable argument would reorder every root in the system.
- **`position` is read-only over the wire.** There is no input for it anywhere in the schema, so a hand-numbered value cannot enter the store through the API.

**Read side.** `sublinkCount` and `sublinks` are two reads of one cached fetch, so the badge cannot disagree with the list it labels. `batch_load_sublink_subtrees` (`schema/loaders.py`) returns each link's whole subtree at any depth, as a flat depth-first list with siblings ordered by `position`. It is never visibility-filtered. Moderation is applied once, in the scalar. It costs one existence probe for the batch plus one `descendants()` CTE per key that has children. The loader is deep-copied per request.

- ⚠️ **`isThreadRoot` is a root marker, not a has-sublinks marker.** It is `parentId is None`, which is also true for every ungrouped link. Do not gate the "N links" chip or the chevron on it. The correct test is `sublinkCount > 0`.
- ⚠️ **`position` has four traps.** It is sibling-scoped, so only comparable within one `parentId`. It is gap-spaced (`10, 20, 30`), not an ordinal, so position 40 does not mean "the fourth". It is not unique: a promoted root can tie, and `0` is the column default for rows written outside `save()`. It is also the only ordering in the schema that is not `occurredAt DESC, id DESC`, so sorting a mixed list by it interleaves unrelated conversations.
- ⚠️ **A hidden middle node suppresses its visible descendants.** `_publicly_visible_subtree` applies the predicate, then drops any descendant of a removed row. A client cannot reach the children of a hidden node, so counting them would make the badge disagree with the list. The pass relies on the loader's depth-first order, so a parent is judged before its children.

**Feed collapse (`collapseThreads`).** Descendants are not adjacent under `occurred_at` order. A flat page is therefore not a superset of whole conversations, and grouping cannot be rebuilt from one page. Paginating over roots and nesting each subtree is the only shape where "every conversation starting here is fully shown" holds. The accepted coupling is that **a conversation is public iff its root is**. Hiding a root hides its whole subtree on a collapsed surface. The console shows `sublinkCount` so an admin sees the effect of a moderation decision first.

**Time windows widen to the subtree, moderation does not.** `currentServiceDayOnly` and `lastWeekOnly` admit a collapsed card when the root **or any descendant, at any depth** falls in the window (`_event_window`, `_event_window_before`). Visibility and `status` are still decided on the root alone. The split is deliberate. A window asks "did anything happen here in this range", and a conversation is in it if any part of it is. A moderation gate asks "may this be shown", and for a shared object, hiding one representative hides the group.

- Trap: grouping elects the **earliest** link as root, so descendants are later. A conversation that opened before the window and got a follow-up inside it would vanish if judged on the root alone.
- Accepted cost: a root admitted only via a descendant renders with its older `occurredAt`. Re-grouping the conversation re-elects the earliest link and fixes the stamp.

**Window subquery implementation** (`schema/resolvers.py::_in_window_subtree_roots`).

- It is an **un-correlated** `pk__in` subquery over the recursive CTE. A correlated `EXISTS` would re-run the recursion for every candidate row.
- ⚠️ Do not use `tree_filter` or `tree_exclude` here. They prune the CTE base, so an out-of-window root is removed before the recursion can reach below it. `tree_path[1]` then returns a descendant, not the conversation root (MISTAKES.md 2026-10-01). The subquery is unfiltered by design. Its cost is bounded by table size, and it runs only when a window flag and `collapseThreads` are both on.
- `lastWeekOnly` closes at today 00:00. `displayTodayInLastWeek` restores the inclusive window. Both apply before `totalCount`.

**Draft-revision flow (`services/incidents.py`).** A non-admin edit of a non-DRAFT incident creates a DRAFT with `parent_incident=incident`, and `created_by` is the editing actor. One open draft per incident: a second actor is rejected, and the same actor resumes their own draft. Admin approval (`approve_incident`) merges fields, M2Ms, chronologies and medias into the parent atomically, then hard-deletes the draft. Admin edits apply in place, and so does an author editing their own `PENDING_APPROVAL` row. `delete_incident` soft-deletes pending children (open drafts, `PENDING_APPROVAL` and `PENDING_DELETION` chronologies) first, because safedelete does not cascade.

**Aggregation (`get_calendar_incidents_by_severity_count`).** It counts `LIVE` incidents whose `start_datetime` date falls in `[startDate, endDate]`, both inclusive. The 60-day guard in the filter does not apply to this resolver.

- **`MONTH`** is a single `GROUP BY` on the (year, month) of `start_datetime` and the severity. Each incident is counted once, in its start month, however long it lasted and whether or not it has ended. Months are independent: a row is not a running total, and January 2025 is not January 2024. An incident that starts inside the window and ends after it still counts in its start month, and months after today are included (planned works). The statement is the same size for any range, so a multi-year window is fine.
- **`DAY`** keeps its exact-date rules. One row per (day, severity, long or short term) from `startDate` to today or `endDate`, whichever is earlier. A long-term incident counts on its start date only. A short-term one counts on every day from its start to its end, or through the last day of that range while it is open-ended. An incident that ends after `endDate` is left out. It builds one conditional `Count(filter=Q(...))` per day × severity × term (via `pendulum` intervals), so the SQL grows linearly with the range, and PostgreSQL refuses more than 1,664 select-list entries: at six per day, a window of 278 days or more with at least one matching incident fails with a `GraphQLError` (`target lists can have at most 1664 entries`). Use `MONTH` for long ranges.
- **`MONTH` is correct for a per-month chart, so a client can read it instead of counting.** It is the count the Insiden "Last 12 months" chart computes client-side from `calendarIncidents` (`insiden-history.queries.ts`, `bucketIncidentsByMonth`): LIVE only, one count per incident in its start month. The one difference is that empty months are absent, so a client still zero-fills its axis. One `calendarIncidentsBySeverityCount(groupBy: MONTH)` read can replace the two aliased year reads and the client-side `status` filter.

**Batching.** `IncidentContextLoaders` is registered under key `"incident"` in `rosak/context.py` and deep-copied per request. It holds six loaders: `medias_from_calendar_incident_loader`, `vote_scores`, `vote_breakdown`, `user_vote_value`, `incident_links` (first page per incident, `first + 1` rows for `hasNextPage`) and `sublink_subtrees`. A new key needs no change in `rosak/context.py`.

### Known integrity risks

- **Duplicate Line ↔ CalendarIncident join.** `CalendarIncident.lines` (`related_name="incidents"`, migration `0013`) and `operation.Line.calendar_incidents` are separate tables. Admin writes the first, and GraphQL `Line.calendarIncidents` reads the second, so that field is always empty. Fix: use `Line.incidents` and remove the field (MISTAKES.md 2026-08-24).
- **`batch_load_medias_from_calendar_incident` returns sets.** The field is typed `List[MediaScalar]`, so duplicates are dropped and the through-table `timestamp` ordering is lost.
- **`last_updated` N+1.** See Outputs.
- `order` is redeclared `editable=True` on the concrete models, and the `# Remove after beta` comment is still open.

Open defects are catalogued in `docs/APPS.md` (Known Defects & Traps) and `MISTAKES.md`.

### Migrations with logic

Latest is `0033` (`PushSubscription`, schema only). The next free number is `0034`. Migrations that carry logic:

- `0004` calendar tier; `0011` `CalendarIncidentMedia` through-model; `0013` `CalendarIncident.lines` gets `related_name="incidents"`.
- `0014` `SocialMediaLink`; `0017` `TextChoicesField` conversion; `0021` `StationIncident` constraint gets `condition=Q(is_last=True)`.
- `0024` / `0025` `normalized_url` backfill (`0025` is a re-backfill, reversible via `noop`); `0026` `LineStatusReport(line, created)` index.
- `0027` official-post ingestion fields and the `system:official-ingest` user.
- `0028` adds `hidden` to status choices (no data change).
- `0029` `Agency` and `SocMedAccount` with seeds, and the `socmed_account` FK move.
- `0030` `occurred_at` (SQL backfill, index `socialmedialink_occurred_idx`).
- `0031` tree (hand-ordered; see the link tree section).
- `0032` data pass: automated `PENDING_APPROVAL` → `LIVE`. `HIDDEN` rows are never touched.

## 🧩 Extension Points & Hooks

- **The abstract triad.** `IncidentAbstractModel`, `IncidentAbstractScalar` and `IncidentAbstractFilter` form a template. A new asset target (for example `AssetIncident` for `operation.Asset` lifts and escalators) needs one model subclass, one scalar subclass, one filter subclass, one field on `IncidentScalars` and one inline in `operation/admin.py`.
- **`IncidentMutations`** is the write seam. New write paths add a mixin.
- **`services/social_link_threads.py`** is the hierarchy seam. Each entry point (`group`, `ungroup`, `reorder`) is one `transaction.atomic()` block. A new affordance (auto-suggest, bulk regroup, move to neighbour) is a new entry point on those blocks. It must assign `position` explicitly, and it must not write ad-hoc `UPDATE`s.
- **`services/social_link_visibility.py::is_publicly_visible`** is the one place the moderation rule changes. New gates call it.
- **`CalendarIncidentCategory`** is a free-form tag table, so new taxonomies need data rows, not migrations. It also backs `SocialMediaLink.categories`.
- **`IncidentContextLoaders`** takes one key per new batched field.
- **`_enqueue_push(incident_id)`** (`services/incidents.py`) is the push seam. A new trigger, such as admin create or official-post ingestion, is one call from inside that write. The task re-checks status and severity, and the per-line cooldown deduplicates.
- **Status enums** are lifecycle hooks. A new state is an enum addition plus the matching service gate. `PassengerStatus` is additive, and its rank is declaration order.
- **`SIGNATURE_CANDIDATES`** is the signed-request seam. X's next signing scheme is one tuple and one env var. CRC uses `_preferred_signing_secret`, because X verifies CRC against exactly one secret.
- **`_expansion_containers`** is the envelope seam. A future envelope nested one level deeper is a one-line change.
- **Pulse knobs** are module constants in `services/line_status.py`: `WINDOW_MINUTES`, `MIN_REPORTS`, `DAY_START_HOUR`, `HOURS_IN_SERVICE_DAY`, `_MAX_PULSE_LINKS`, `MAX_LINES_PER_HISTORY_REQUEST`, `MAX_HISTORY_DAYS_AGO`, `DEFAULT_WEEK_PROFILE_WEEKS`, `MAX_WEEK_PROFILE_WEEKS`. New tracking parameters go in `TRACKING_PARAMS` (`services/urls.py`).
- **`impact_factor`** is a reserved hook with zero consumers. Its `help_text` says scores are deducted from 100 per day, prorated by service hours. See Feature 2.
- **Evidence channel.** `CalendarIncidentChronology.source_url` and the `/upload/` → `common.tasks` → `CalendarIncidentMedia` pipeline (with EXIF timestamp capture) are ready for any citation or verification workflow.
- **Presentation flags.** `inaccurate` and `long_term` are honoured by the frontend. Automated writers can use them as provisional markers without new schema.
- **Manual ordering.** `ordered_model` gives editors `move_up_down_links` control over the asset ledger, independent of chronology.

## 💡 Potential Feature Opportunities

1. **"All incidents in this disruption": one FK to join the two tiers.** A reader viewing a network disruption cannot see which vehicles or stations it affected, and an editor cannot attach a vehicle fault to an open disruption. Add a nullable `calendar_incident` FK on `IncidentAbstractModel` (`on_delete=SET_NULL`). This gives `CalendarIncidentScalar` rollup lists and each asset scalar a parent link, and makes `impact_factor` attributable to specific rolling stock. Only `CalendarIncidentChronology` has a `calendar_incident` FK today.
   **Readiness:** `Not ready`. Add the field to `IncidentAbstractModel` in `incident/models.py`. Generate migration `0034`. It is nullable, so no backfill. Add the fields to `VehicleIncident`, `StationIncident` and `CalendarIncidentScalar` in `incident/schema/scalars.py`, a nested filter in `incident/schema/filters.py`, and `autocomplete_fields` on the inlines in `incident/admin.py`. `CalendarIncidentAdmin` already has `search_fields`.

2. **Per-line reliability score from `impact_factor`.** Full spec in `docs/features/04-impact-factor-reliability.md`. The column, admin field, GraphQL field and ordering key are all wired, and nothing consumes them.
   **Readiness:** `Partially ready`. (a) The "prorated by usual service hours" half has no data source. `operation.Line` has no service-hours field, so either use whole-day denominators in v1 or add `service_start_time` / `service_end_time`. (b) The resolver must traverse `CalendarIncident.lines` (reverse accessor `Line.incidents`), not `operation.Line.calendar_incidents`, which admin never writes. Files: `incident/schema/resolvers.py`, `incident/schema/schema.py`, optionally `operation/schema/scalars.py`.

3. **Public status page and subscribable disruption feed (ICS, Atom, RSS).** `CalendarIncident` has what a feed needs: `start_datetime`, a nullable `end_datetime` that means "still ongoing", `severity`, `title`, `details`, `inaccurate`, `long_term`, and ordered chronology rows with `datetime`, `indicator`, `content` and `source_url`. The `activeNow` and `ongoing` filters and the per-line pulse (`operation.Line` pulse fields) supply the live "is it broken right now" half.
   **Readiness:** `Partially ready`. Missing: a feed URL. Add `incident/urls.py` with a `django.contrib.syndication.views.Feed` subclass and a `text/calendar` view, then one `path("incident/", include("incident.urls"))` in `rosak/urls.py`.

4. **Asset incidents on the map, with photo evidence.** `IncidentAbstractModel.location` is a real `PointField` that editors already fill in through `VehicleIncidentLocationForm` and `StationIncidentLocationForm`. Both asset models carry a `medias` M2M to `common.Media`. Both are commented out in `incident/schema/scalars.py` (`location` and `medias`), so the data is invisible to clients.
   **Readiness:** `Ready`. No migration. Declare `location: Optional["GeoPoint"]` on the asset scalar, as `operation.schema.scalars.Station` does, and `medias` as a lazy `MediaScalar` list. These are plain M2Ms, so `DjangoOptimizerExtension` prefetches them and no DataLoader is needed. Single file: `incident/schema/scalars.py`.

5. **Station incident history.** The vehicle side has `incident_from_vehicle_loader` and `incident_count_from_vehicle_loader` (`operation/schema/loaders.py`), which back `Vehicle.incidents`, `incidentCount` and `canExpand`. The station side has neither, so `operation.schema.scalars.Station` has no `incidents` field. Only the root `stationIncidents` query reaches station incidents.
   **Readiness:** `Ready`. Add station variants of the two batch functions, register them in `OperationContextLoaders`, and add `incidents` and `incidentCount` to `Station`. The unique constraint is already correct.

## 💡 Potential AI Feature Opportunities

1. **Auto-draft calendar incidents from operator announcements.** `telegram_provider` ingests operator channel messages, and `operation.Line` carries `telegram_channel_id`, but nothing bridges into `incident`. An LLM step could propose a `CalendarIncident` (span, `severity`, affected lines and stations, `title`, `brief`) plus `CalendarIncidentChronology` rows, writing through `IncidentMutations`. `extractDataFromUrl` already demonstrates the pattern. Set `inaccurate=True` as the low-confidence marker, and use chronology `source_url` for citation.
2. **Impact scoring.** A model trained on span length, affected-line count, chronology length and severity could suggest an `impact_factor` at admin-save time. That would populate the dormant column and feed a per-line reliability index.
3. **Semantic clustering and cross-tier linkage.** `title`, `brief`, `details` and chronology text, plus `CalendarIncidentCategory`, make the app embedding-ready. Uses: suggest categories, detect duplicates of an open incident, support natural-language search, and infer which asset ledger rows belong to which calendar incident from shared asset and date. That inferred relation is the FK Feature 1 would add.

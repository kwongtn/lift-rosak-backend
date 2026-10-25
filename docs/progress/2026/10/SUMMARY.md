# Monthly Summary - October 2026

Total commits: 15 non-merge Oct 1–20 (`git log --no-merges`, counted 2026-10-21). Markers follow each daily file: `(this commit)`, `(uncommitted)`, or a hash.

## Commit Type Distribution (logged entries)

- feat: 7
- fix: 10
- docs: 4
- no type given: 1

## Daily Logs

- [01.md](01.md): nested social-link tree, `lastWeekOnly` midnight cut, migration 0031 fix, vote payloads, `/spot` matching, month-boundary test fix.
- [03.md](03.md): network and multi-line status history queries.
- [08.md](08.md): official posts auto-publish as `LIVE`; console `hidden` filter.
- [19.md](19.md): front-page pulse-link N+1 fix; pytest run leaves the kept test DB broken.
- [20.md](20.md): `Vehicle.lastSpottedAt` tiebreaker.
- [21.md](21.md): docs squash to current state; `updateUser` null guard, Telegram settings coercion, `argparse.ArgumentError`, `report_spotting_today` date fix; daily digest sends again (DISTINCT ON crash, per-loop PTB app); lines may share a Telegram channel. Frontend audit fix pass, backend side: `media(id)`, anonymous-spotting privacy, GPS strip, GROUP BY year counts, review follow-ups; every image accepted again, HEIC included.
- [22.md](22.md): feature pass, backend side of the rosak_firebase 2026-10-21 audit: `calendarIncidents` filters (`activeNow`, `upcomingWithinDays`, `lines`, `stations`, `status`), `Asset.status` enum, `daysAgo` and `lineStatusWeekProfile`, web push subscriptions and MAJOR-incident alerts, per-month severity aggregate, medias paging tie-break, `Asset.station`.
- [24.md](24.md): daily digest moves to 03:01 and covers the 27-hour service day by submission time; `/spotting_today` unchanged; component docs follow. Kuala Lumpur time sweep: aware client datetimes normalised to naive KL, official-post CLI days in KL, `get_trends` end resolved per call.

## By Module/Feature

### Kuala Lumpur time sweep (Oct 24, incident / common)

- **decc83f** `[fix](incident)`: incident and chronology datetimes pass through `shared.naive_kl`, so an aware client value (`...Z`) no longer misses the stored naive one in `replace_chronologies`, and a pending deletion or approval survives an admin resave.
- **1298dd5** `[fix](incident)`: `ingest_official_posts` and `export_official_posts` read `--since` / `--until` as Kuala Lumpur days (they were UTC days); `fetch_user_posts` still sends UTC to the X API. **8086023** `[docs](incident)`: the history entry timestamp is naive KL, not UTC. **0551419** `[fix](common)`: `get_trends` resolves `end` at call time.
- Docs: **0e47d9e** (progress entry, MISTAKES trap, APPS.md row, incident and common component docs).
- Full serial suite 712 → 725 tests, OK; ruff, `manage.py check` and `makemigrations --check` clean. ([24.md](24.md))

### Digest window (Oct 24, spotting)

- **f03d8d8** `[feat](spotting)`: `report_spotting_today` fires at 03:01 (was 00:00) and digests the 27-hour service day `[D 03:01, D+1 03:01)` by `Event.created`, headed D. `get_daily_updates` gains a keyword-only `created_between`; `/spotting_today` keeps its `spotting_date` and 03:00 cutoff.
- Docs: **f46024a** (progress entry, APPS.md beat row, component docs, MISTAKES pin).
- Full serial suite 686 → 692 tests, OK; ruff, `manage.py check` and `makemigrations --check` clean. ([24.md](24.md))

### Feature pass (Oct 22, backend side of the rosak_firebase 2026-10-21 audit feature pass)

- **699126d**, **4d30b6b**, **07c8289** `[feat](incident)`: `CalendarIncidentFilter` gains `activeNow`, `upcomingWithinDays` (1 to 60), nested `lines` / `stations` (pk-IN subqueries over the through tables, one row per incident) and `status` (F077, F293). **b8a56ab** `[fix](operation)`: `StationFilter.stationLine` resolves the `stationline` relation. The root `calendarIncidents` field still has no status gate; public readers send `status: LIVE`.
- **7e9fc20**, **3b2b949** `[feat](operation)`: `Asset.status` is a `TextChoicesField` enum (`IN_OPERATION`, `UNDER_MAINTENANCE`) with an `AssetFilter.status`; migration `0019` refuses rows outside the enum before the no-op `AlterField` (F597 phase 1).
- **19db35f**, **0755450**, **5f94ae8** `[feat](incident)`: `daysAgo` (0 to 56) on `lineStatusHistory`, `networkStatusHistory` and `linesStatusHistory`; `lineStatusWeekProfile(lineId, weeks, dayStartHour)` returns 168 service-day weekday-hour buckets (F213 slice 2).
- **ce3d947**, **4d66938** `[feat](incident)`: `PushSubscription` (token, user, lines), `registerPushToken` / `unregisterPushToken` / `pushSubscription` (login required, 2048-character tokens, 20 per user), Celery `notify_push_subscribers` sent through `firebase_admin.messaging` on a MAJOR approval, one push per line per 30 minutes via `cache.add`, transient FCM errors re-raised so `autoretry_for` fires, stale tokens pruned (F294).
- **9832a3d** `[fix](incident)`: `calendarIncidentsBySeverityCount(groupBy: MONTH)` counts LIVE incidents once per (year, month) instead of a running total that reset each January. **7a02ef4** `[fix](common)`: the medias feed appends the primary key to every order, so paging neither repeats nor skips. **6ac24b8** `[fix](operation)`: `Asset.station` replaces the always-failing `Asset.stations` (breaking change recorded in the snapshot allowlist).
- Docs: **880ec5b**, **82c2f28**, **ea05787**, **45891e3** (progress entry, 12 MISTAKES traps, APPS.md defect rows), **13e8ddb**.
- Full serial suite 601 → 686 tests, OK; ruff, `manage.py check` and `makemigrations --check` clean. ([22.md](22.md))

### Audit fix pass (Oct 21, backend side of the rosak_firebase 2026-10-21 audit)

- **0ed9baf** `[feat](common)`: `media(id: ID!)` root query for single-photo deep links (F049).
- **0a830bf**, **d94380f**, **73b1006** `[fix](spotting, common)`: an anonymous spotting hides its location, its public-profile rows and counts, and its photos' uploader (now nullable) from everyone but the reporter and admins (F043). **0ebb6c7**: `withMostEntries` is nullable instead of erroring. **3bd4bbf**: a Firebase error in the admin check fails closed.
- **32835a3**, **45a3075**, **6d8ad08** `[fix](common)`: lossless EXIF GPS strip at upload, in the Telegram handler and before the Discord send, with a bounded loop; HEIC uploads refused (F044). **ae696dd** reverts the refusal at the owner's request: HEIC and every other non-JPEG upload is stored as received, GPS included. **ec2dc9a**: Telegram stages an image document by its extension when its mime type is generic. **1eab6e7**: the EXIF DateTime is parsed before it reaches `CalendarIncidentMedia.timestamp`.
- **9f326fd**, **69ecc4e** `[perf](common)`: `mediasGroupByPeriod` uses one GROUP BY (42-59 s locally before, 0.2-0.5 s after) and skips fileless rows (F012). **3936a07**: fileless media are hidden from `medias` and `media(id)`. **64b7435**: `createdDate` no longer costs one query per photo.
- **d9e429b** `[fix](rosak)`: GraphQL GET responses vary on `Firebase-Auth-Key`, so the per-site cache never serves one viewer's data to another.
- Full serial suite 553 → 601 tests, OK. ([21.md](21.md))

### Incident (8 entries)

- (this commit) `[fix](incident)`: migration `0031_socialmedialink_tree_parent_and_more` aborted on threaded rows (deferred FK trigger events blocked its DDL). Each `RunPython` half now flushes constraints, covered by an executor round-trip test. Staging stays at `0030` until the fixed commit deploys. ([01.md](01.md))
- (this commit) `[feat](incident)`: `publicSocialMediaLinks.lastWeekOnly` closes at calendar midnight (last six completed days); new `displayTodayInLastWeek` restores the inclusive window. ([01.md](01.md))
- (this commit) `[fix](incident)`: V1 review of the above; documents the `currentServiceDayOnly` intersection (pinned by a test) and makes fixtures clock-proof. ([01.md](01.md))
- (this commit) `[feat](incident)`: `SocialMediaLink` threads become an ordered nested tree (`django-tree-queries`, `parent` and `position`, no cycles, depth <= 3, `reorderSocialMediaLinks`). Breaking GraphQL change, no aliases. ([01.md](01.md))
- (this commit) `[feat](incident)`: the nine vote mutations return `VoteMutationPayload` (vote state and score) instead of a bare `ok`. ([01.md](01.md))
- (this commit) `[feat](incident)`: `networkStatusHistory` and `linesStatusHistory`, both read through one `_service_day_entries` helper. ([03.md](03.md))
- (this commit) `[feat](incident)`: official posts ingest as `LIVE` (migration `0032` backfill); console `socialMediaLinks(hidden:)` filter. ([08.md](08.md))
- (uncommitted) `[fix](incident)`: front-page `lines` query N+1 on pulse links fixed in `_links_by_id`, pinned by a query-count test. ([19.md](19.md))

### Operation (2 entries)

- (this commit) `[fix](operation)`: `Vehicle.lastSpottedAt` tiebreaker for same-day sightings; the date-only `lastSpottingDate` had left seven vehicles tied. ([20.md](20.md))
- **d0a2dd9** `[feat](operation)`: `Line.telegram_channel_id` no longer unique (migration `0018`, drops by column); `report_spotting_today` sends one digest per channel, for its first line by code. ([21.md](21.md))

### Common (1 entry)

- `test_get_user_data_query_profile_aggregates` fixture failed on the 1st of each month; the second fixture day is now month-relative. ([01.md](01.md))

### Telegram Provider (1 entry)

- (this commit) `[feat](telegram_provider)`: `/spot` matches vehicles on an exact key after space normalisation; `/spot 01` no longer matches `011` or `012`. ([01.md](01.md))

### Fixes (Oct 21, 6 entries)

- **d7890ba** `[fix](common)`: `updateUser` rejects explicit `null` for `spotting_data_public` instead of a NOT NULL IntegrityError. ([21.md](21.md))
- **7ff07fa** `[fix](telegram_provider)`: `TELEGRAM_CLEANUP_DAYS` / `TELEGRAM_HTTPX_TIMEOUT` coerced from env. ([21.md](21.md))
- **f408119** `[fix](spotting)`: `report_spotting_today` digests the day that just ended (`effective_spotting_date`); digest heading shows that date. ([21.md](21.md))
- **ab9f248** `[fix](telegram_provider)`: `argparse.ArgumentError` replaces `ctypes.ArgumentError`. ([21.md](21.md))
- **4a0ae91** `[fix](telegram_provider)`: lazy PTB app cached per event loop; Celery sends no longer hit `Event loop is closed`. ([21.md](21.md))
- **6238a77** `[fix](spotting)`: `report_spotting_today` no longer crashes on DISTINCT ON vs `Line.Meta.ordering`, so the daily digest sends; test shim removed. ([21.md](21.md))

### Docs (3 entries)

- **ffd0903** `[docs]`: docs squash to current state; `tach.yml` references removed (it never existed), beat schedule and `Asia/Kuala_Lumpur` timezone corrected, uncapped media-task re-enqueue and NSFW/convert race catalogued as traps. ([21.md](21.md))
- **812d2ec** `[docs]`: obsolete upgrade record and doc-generation prompts dropped; **379aa4c** progress summaries condensed. ([21.md](21.md))
- **59fef14** `[docs]`: four fixed traps marked resolved. ([21.md](21.md))

### Test gate and traps (2 entries)

- Full serial suite is 537 tests. After any pytest run, run `manage.py test` without `--keepdb`. ([19.md](19.md))
- Freezing `django.utils.timezone.now` does not freeze `auto_now_add`. ([03.md](03.md))

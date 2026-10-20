# Monthly Summary - October 2026

Total commits: 15 non-merge Oct 1–20 (`git log --no-merges`, counted 2026-10-21). Markers follow each daily file: `(this commit)`, `(uncommitted)`, or a hash.

## Commit Type Distribution (logged entries)

- feat: 6
- fix: 8
- docs: 4
- no type given: 1

## Daily Logs

- [01.md](01.md): nested social-link tree, `lastWeekOnly` midnight cut, migration 0031 fix, vote payloads, `/spot` matching, month-boundary test fix.
- [03.md](03.md): network and multi-line status history queries.
- [08.md](08.md): official posts auto-publish as `LIVE`; console `hidden` filter.
- [19.md](19.md): front-page pulse-link N+1 fix; pytest run leaves the kept test DB broken.
- [20.md](20.md): `Vehicle.lastSpottedAt` tiebreaker.
- [21.md](21.md): docs squash to current state; `updateUser` null guard, Telegram settings coercion, `argparse.ArgumentError`, `report_spotting_today` date fix.

## By Module/Feature

### Incident (8 entries)

- (this commit) `[fix](incident)`: migration `0031_socialmedialink_tree_parent_and_more` aborted on threaded rows (deferred FK trigger events blocked its DDL). Each `RunPython` half now flushes constraints, covered by an executor round-trip test. Staging stays at `0030` until the fixed commit deploys. ([01.md](01.md))
- (this commit) `[feat](incident)`: `publicSocialMediaLinks.lastWeekOnly` closes at calendar midnight (last six completed days); new `displayTodayInLastWeek` restores the inclusive window. ([01.md](01.md))
- (this commit) `[fix](incident)`: V1 review of the above; documents the `currentServiceDayOnly` intersection (pinned by a test) and makes fixtures clock-proof. ([01.md](01.md))
- (this commit) `[feat](incident)`: `SocialMediaLink` threads become an ordered nested tree (`django-tree-queries`, `parent` and `position`, no cycles, depth <= 3, `reorderSocialMediaLinks`). Breaking GraphQL change, no aliases. ([01.md](01.md))
- (this commit) `[feat](incident)`: the nine vote mutations return `VoteMutationPayload` (vote state and score) instead of a bare `ok`. ([01.md](01.md))
- (this commit) `[feat](incident)`: `networkStatusHistory` and `linesStatusHistory`, both read through one `_service_day_entries` helper. ([03.md](03.md))
- (this commit) `[feat](incident)`: official posts ingest as `LIVE` (migration `0032` backfill); console `socialMediaLinks(hidden:)` filter. ([08.md](08.md))
- (uncommitted) `[fix](incident)`: front-page `lines` query N+1 on pulse links fixed in `_links_by_id`, pinned by a query-count test. ([19.md](19.md))

### Operation (1 entry)

- (this commit) `[fix](operation)`: `Vehicle.lastSpottedAt` tiebreaker for same-day sightings; the date-only `lastSpottingDate` had left seven vehicles tied. ([20.md](20.md))

### Common (1 entry)

- `test_get_user_data_query_profile_aggregates` fixture failed on the 1st of each month; the second fixture day is now month-relative. ([01.md](01.md))

### Telegram Provider (1 entry)

- (this commit) `[feat](telegram_provider)`: `/spot` matches vehicles on an exact key after space normalisation; `/spot 01` no longer matches `011` or `012`. ([01.md](01.md))

### Fixes (Oct 21, 4 entries)

- **d7890ba** `[fix](common)`: `updateUser` rejects explicit `null` for `spotting_data_public` instead of a NOT NULL IntegrityError. ([21.md](21.md))
- **7ff07fa** `[fix](telegram_provider)`: `TELEGRAM_CLEANUP_DAYS` / `TELEGRAM_HTTPX_TIMEOUT` coerced from env. ([21.md](21.md))
- **f408119** `[fix](spotting)`: `report_spotting_today` digests the day that just ended (`effective_spotting_date`); digest heading shows that date. ([21.md](21.md))
- **ab9f248** `[fix](telegram_provider)`: `argparse.ArgumentError` replaces `ctypes.ArgumentError`. ([21.md](21.md))

### Docs (3 entries)

- **ffd0903** `[docs]`: docs squash to current state; `tach.yml` references removed (it never existed), beat schedule and `Asia/Kuala_Lumpur` timezone corrected, uncapped media-task re-enqueue and NSFW/convert race catalogued as traps. ([21.md](21.md))
- **812d2ec** `[docs]`: obsolete upgrade record and doc-generation prompts dropped; **379aa4c** progress summaries condensed. ([21.md](21.md))
- **59fef14** `[docs]`: four fixed traps marked resolved. ([21.md](21.md))

### Test gate and traps (2 entries)

- Full serial suite is 537 tests. After any pytest run, run `manage.py test` without `--keepdb`. ([19.md](19.md))
- Freezing `django.utils.timezone.now` does not freeze `auto_now_add`. ([03.md](03.md))

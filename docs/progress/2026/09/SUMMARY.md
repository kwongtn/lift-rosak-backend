# Monthly Summary - September 2026

Total commits: 100 non-merge (`git log --no-merges`, counted 2026-10-21). The listing below covers logged entries; entries marked `no daily log` have no day file.

## Commit Type Distribution (logged entries)

- feat: 30
- fix: 8
- test: 2
- chore: 2

## Daily Logs

- [12.md](12.md): 11 commits, video in the temporary media pipeline, `AWAITING_REVIEW` status, Telegram `/approve` and photo/video auto-attach.
- [13.md](13.md): uncommitted, legacy incident and chronology rows backfilled to `LIVE`.
- [15.md](15.md): uncommitted, OCI Object Storage rejected aws-chunked uploads; boto3 checksum calculation disabled.
- [16.md](16.md): uncommitted, submitter link edits return to review, `/spotting_today` not-in-service flag, media queued while uploads are off, `/approve` on `/link` replies.
- [22.md](22.md): line status reports and pulse, canonical social-link URLs, feed submit and votes, full-day status history, service-day feed filter, seeded demo data, Firebase credential mount.
- [23.md](23.md): admin-only `deleteSocialMediaLink`, `statusCounts` docs.
- [24.md](24.md): `/spotting_today` fixes and 3am cutoff, `LineAdmin` change form, Python 3.13, celerybeat credential mount, dependency refresh, 7 failing tests fixed, `has_admin_claim` fix.
- [26.md](26.md): official-post ingestion, Phases 1 to 3.
- [28.md](28.md): X webhook receiver, webhook `includes` fix, polling opt-in, `HIDDEN` status and `isAutomated`, entity decoding, Agency/SocMedAccount registry.
- [30.md](30.md): `occurred_at` event time, `lastWeekOnly` and `alignPageToDay`, feed ordering on `occurred_at`, thread grouping.

## By Module/Feature

### Incident (35 entries)

- (this commit) `[feat](incident)`: `SocialMediaLink.occurred_at` event time (migration `0030`) becomes the ordering and window instant; first thread grouping (`groupSocialMediaLinks`, `collapseThreads`).
- (this commit) `[feat](incident)`: `publicSocialMediaLinks` gains `lastWeekOnly` and `alignPageToDay`.
- (this commit) `[fix](incident)`: decode HTML entities once at the ingest boundary.
- (this commit) `[feat](incident)`: hide links from the public feed (`HIDDEN`) and expose `isAutomated`.
- (this commit) `[fix](incident)`: read the X webhook `includes` expansion from `data`; every real delivery had been dropped.
- (this commit) `[feat](incident)`: X Activity API webhook receiver (`/webhooks/x-api`) and `x_webhook` command.
- (this commit) `[feat](incident)`: official-post polling is opt-in (`OFFICIAL_POST_POLLING_ENABLED`).
- (this commit) `[feat](incident)`: official-post Phase 3, `export_official_posts` (JSONL/CSV, optional HuggingFace push).
- (this commit) `[feat](incident)`: official-post Phase 2, admin Telegram notify per ingested post and approval-gated public feed.
- **c23e7bc** `[feat](incident)`: official post ingestion foundation.
- (this commit) `[feat](incident)`: scheduled official-post ingestion task and backfill command.
- (this commit) `[feat](incident)`: `Agency` and `SocMedAccount` registry replaces `OFFICIAL_POST_HANDLES` (migration `0029`).
- (uncommitted) `[feat](incident)`: submitter `SocialMediaLink` edit; admin edits land `LIVE`, submitter edits return to `PENDING_APPROVAL`.
- (uncommitted) `[fix](incident)`: backfill legacy incident and chronology rows to `LIVE` (migrations `0015`/`0016`).
- (no daily log) `[fix](incident)`: date range filter returns inclusive interval overlap (`e514baa`).
- **32b7686** `[feat](incident)`: admin-only `deleteSocialMediaLink`.
- (this commit) `[docs](incident)`: `statusCounts` names the reused `PassengerStatusCount` type.
- (this commit) `[fix](incident)`: `lineStatusHistory` returns the full 24-hour service day.
- (this commit) `[feat](incident)`: per-status report counts on a line (`Line.passengerStatusCounts`).
- (this commit) `[feat](incident)`: public feed `currentServiceDayOnly` and cursor-independent `totalCount`.
- (this commit) `[feat](incident)`: per-status breakdown (`statusCounts`) on each hourly history bucket.
- **f3fb273** `[feat](incident)`: `PassengerStatus` enum, `LineStatusReport`, `normalized_url`.
- **e0884ae** `[feat](incident)`: canonicalize social link URLs.
- **ab7af0e** `[feat](incident)`: deterministic line-status consolidation.
- **1a9737e** `[feat](incident)`: social link vote service wrappers.
- **145778b** `[feat](incident)`: link vote state on the scalar; feed status filter.
- **f0ded00** `[feat](incident)`: feed link submit with dedup and auto-upvote.
- **a62ed6d** `[feat](incident)`: line status report and page title services.
- **a9418c5** `[feat](incident)`: feed submit and line status report mutations.
- **67a830c** `[feat](incident)`: complete incident reporting backend (no daily log).
- **b9bd6fd** `[feat](incident)`: public `publicSocialMediaLinks` query with line filter (no daily log).
- **1533846** `[feat](incident)`: admin can fully edit a `SocialMediaLink` before completion (no daily log).
- **990d89c** `[feat](incident)`: `status` on `CalendarIncidentScalar` (no daily log).
- **f1b89ec** `[fix](incident)`: coerce null details/title/brief to empty string (no daily log).
- **799ea77** `[fix](incident)`: coerce null title to empty string for `SocialMediaLink` (no daily log).

### Operation (2 entries)

- **7c813fe** `[feat](operation)`: per-line pulse fields and DataLoaders.
- (uncommitted) `[fix](operation)`: `LineAdmin` excludes `calendar_incidents` from the change form (slow page loaded every incident).

### Spotting (1 entry)

- **46cfde5** `[fix](spotting)`: mount the firebase credential from the real home path.

### Common (9 entries)

- (this commit) `[chore](common)`: seed same-hour status variety and station-tagged reports.
- (this commit) `[chore](common)`: seed hundreds of varied reports across lines.
- **010428c** `[test](common)`: cover video pipeline and bounded cleanup.
- **82addcc** `[feat](common)`: support video in temporary media pipeline.
- **a9f1067** `[feat](common)`: hold `AWAITING_REVIEW` media from auto-conversion.
- **511afaa** `[feat](common)`: expose media caption, duration and type on `MediaScalar`.
- **9ba0763** `[feat](common)`: add caption and duration to Media; widen `content_type`.
- **a531e51** `[feat](common)`: add `AWAITING_REVIEW` temporary media status.
- (uncommitted) `[fix](common)`: disable boto3 trailer checksums for OCI S3-compat (aws-chunked 501).

### Telegram (9 entries)

- **82e5c3f** `[test](telegram)`: cover media upload and `/approve`.
- **ed9c461** `[feat](telegram)`: register media handler and `/approve` command.
- **ea49424** `[feat](telegram)`: `/approve` for reviewed media.
- **a82de20** `[feat](telegram)`: auto-attach incoming photo/video to latest spotting.
- **6075118** `[fix](telegram)`: `/spotting_today` referenced a non-existent `VehicleStatus` member; now excludes `OUT_OF_SERVICE`.
- **42d8b12** `[feat](telegram)`: `/spotting_today` service-day cutoff (3am default).
- (uncommitted) `[feat](telegram)`: `/spotting_today` excludes not-in-service by default; `--include-not-in-service` opt-in.
- (uncommitted) `[feat](telegram)`: media always recorded as `TemporaryMedia`, even while uploads are disabled.
- (uncommitted) `[feat](telegram)`: `/approve` on a replied `/link` message approves the link.

### Ci (1 entry)

- **6fd0d1a** `[fix](ci)`: publish full commit hash for version endpoint (no daily log).

### Rosak (2 entries)

- **0ff57ec** `[chore](rosak)`: refresh GraphQL schema snapshot for media fields.
- **6a8f25e** `[fix](rosak)`: `has_admin_claim` denies a missing Firebase account instead of raising.

### Python (1 entry)

- **bc45bf1** `[chore](python)`: upgrade runtime to Python 3.13.

### Compose (1 entry)

- **2acbbc2** `[fix](compose)`: mount firebase credentials into celerybeat.

### Deps (1 entry)

- **fc72187** `[chore](deps)`: refresh pinned dependencies (pendulum 3.2).

### Test (1 entry)

- **51f2f69** [test]: mock the Firebase admin check in the 7 failing tests.

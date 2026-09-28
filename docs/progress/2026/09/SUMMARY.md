# Monthly Summary - September 2026

Total commits: 38

## Commit Type Distribution

- feat: 28
- fix: 6
- test: 2
- chore: 2

## By Module/Feature

### Incident (23 commits)

- (this commit) [feat](incident): receive X Activity API webhook deliveries — `GET/POST /webhooks/x-api` (CRC challenge, HMAC-SHA256 over raw bytes, `post.create` → `SocialMediaLink`, queued Telegram notification, idempotent on redelivery) + the `x_webhook` management command for registration/subscriptions; 70 new tests, + docs (attribution rules, env matrix, CRC troubleshooting) and a MISTAKES entry for the debug-toolbar/Redis-cache test traps
- (this commit) [feat](incident): make official-post polling opt-in via `OFFICIAL_POST_POLLING_ENABLED` — webhooks are the primary path
- (this commit) [feat](incident): official-post Phase 3 — `export_official_posts` writes the ingested archive as JSONL/CSV (streamed, stable order, `raw_payload` opt-in, `--dry-run`, optional private `push_to_hub`); 28 tests, + docs (naive-local `posted_at` trap)
- (this commit) [feat](incident): official-post Phase 2 — Telegram the admin per newly ingested post (reply `/approve`-able via `send_message(return_log=True)` + `TelegramSocialMediaLinkLog`), and exclude automated `PENDING_APPROVAL` posts from the public feed (+ docs: corrected the stale "outbound is ungoverned" claims in APPS.md and the component docs)
- **c23e7bc** [feat](incident): official post ingestion foundation
- (this commit) [feat](incident): scheduled official-post ingestion task, backfill command and tests (+ docs: beat table 8 → 9 jobs, ingestion service paragraph, "pending is public" trap)
- **67a830c** [feat](incident): complete insiden reporting backend
- **b9bd6fd** [feat](incident): add public publicSocialMediaLinks GraphQL query with line filter
- **1533846** [feat](incident): allow admin to fully edit SocialMediaLink before completion
- **990d89c** [feat](incident): expose status on CalendarIncidentScalar
- **f1b89ec** [fix](incident): coerce null details/title/brief to empty string for CalendarIncident
- **799ea77** [fix](incident): coerce null title to empty string for SocialMediaLink
- (uncommitted) [fix](incident): backfill legacy incident/chronology rows to LIVE in migrations 0015/0016
- (uncommitted) [feat](incident): submitter SocialMediaLink edit — admin lands live, submitter forced back to PENDING_APPROVAL (Task 24)
- (uncommitted) [fix](incident): date range filter returns inclusive interval overlap (was dropping incidents ending before / starting after the window); tests added
- **f3fb273** [feat](incident): add PassengerStatus enum, LineStatusReport, normalized_url
- **e0884ae** [feat](incident): canonicalize social link URLs
- **ab7af0e** [feat](incident): deterministic line-status consolidation
- **1a9737e** [feat](incident): social link vote service wrappers
- **145778b** [feat](incident): expose link vote state and add feed status filter
- **f0ded00** [feat](incident): feed link submit with dedup and auto-upvote
- **a62ed6d** [feat](incident): line status report and page title services
- **a9418c5** [feat](incident): feed submit and line status report mutations
- (this commit) [feat](incident): expose per-status report counts on a line
- (this commit) [fix](incident): return every hour of the service day in the status history
- (this commit) [feat](incident): filter the public feed by service day and expose total counts
- (this commit) [feat](incident): expose a per-status breakdown on each hourly history bucket
- (this commit) [docs](incident): name the reused `operation.schema.scalars.PassengerStatusCount` in the hourly-bucket docs (docs-only follow-up to `22baa99`)
- **32b7686** [feat](incident): admin-only `deleteSocialMediaLink` mutation removes a feed link

### Operation (1 commits)

- **7c813fe** [feat](operation): per-line pulse fields and DataLoaders
- (uncommitted) [fix](operation): exclude `calendar_incidents` from `LineAdmin` change form (slow page loaded every incident; field no longer required)

### Spotting (1 commits)

- **46cfde5** [fix](spotting): mount the firebase credential from the real home path

### Common (7 commits)

- (this commit) [chore](common): seed same-hour status variety and more station-tagged reports
- (this commit) [chore](common): seed hundreds of varied reports across lines
- **010428c** [test](common): cover video pipeline and bounded cleanup
- **82addcc** [feat](common): support video in temporary media pipeline
- **a9f1067** [feat](common): hold AWAITING_REVIEW media from auto-conversion
- **511afaa** [feat](common): expose media caption/duration/type on MediaScalar
- **9ba0763** [feat](common): add caption/duration to Media and widen content_type
- **a531e51** [feat](common): add AWAITING_REVIEW temporary media status
- (uncommitted) [fix](common): disable boto3 trailer checksums for OCI S3-compat (aws-chunked 501)

### Telegram (5 commits)

- **82e5c3f** [test](telegram): cover media upload + /approve
- **ed9c461** [feat](telegram): register media handler and /approve command
- **ea49424** [feat](telegram): add /approve for reviewed media
- **a82de20** [feat](telegram): auto-attach incoming photo/video to latest spotting
- **6075118** [fix](telegram): `/spotting_today` referenced a non-existent `VehicleStatus` member — now excludes `OUT_OF_SERVICE`
- (uncommitted) [feat](telegram): /spotting_today excludes not-in-service by default with `--include-not-in-service`/`--inis` opt-in; media uploads always record a TemporaryMedia row while uploads disabled; /approve on a replied /link message approves the link
- **42d8b12** [feat](telegram): `/spotting_today` service-day cutoff — 3am default (pre-3am counts as previous day), `--use-actual-date`, `--cutoff=HHMM`; explicit date never shifted

### Ci (1 commits)

- **6fd0d1a** [fix](ci): publish full commit hash for version endpoint

### Rosak (2 commits)

- **0ff57ec** [chore](rosak): refresh GraphQL schema snapshot for media fields
- **6a8f25e** [fix](rosak): treat a missing firebase account as non-admin

### Python (1 commits)

- **bc45bf1** [chore](python): upgrade runtime to Python 3.13

### Compose (1 commits)

- **2acbbc2** [fix](compose): mount firebase credentials into celerybeat

### Deps (1 commits)

- **fc72187** [chore](deps): refresh pinned dependencies

### Test (1 commits)

- **51f2f69** [test]: mock the firebase admin check in the 7 failing tests

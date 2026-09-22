# Monthly Summary - September 2026

Total commits: 32

## Commit Type Distribution

- feat: 23
- fix: 5
- test: 2
- chore: 2

## By Module/Feature

### Incident (17 commits)

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

### Operation (1 commits)

- **7c813fe** [feat](operation): per-line pulse fields and DataLoaders

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

### Telegram (4 commits)

- **82e5c3f** [test](telegram): cover media upload + /approve
- **ed9c461** [feat](telegram): register media handler and /approve command
- **ea49424** [feat](telegram): add /approve for reviewed media
- **a82de20** [feat](telegram): auto-attach incoming photo/video to latest spotting
- (uncommitted) [feat](telegram): /spotting_today excludes not-in-service by default with `--include-not-in-service`/`--inis` opt-in; media uploads always record a TemporaryMedia row while uploads disabled; /approve on a replied /link message approves the link

### Ci (1 commits)

- **6fd0d1a** [fix](ci): publish full commit hash for version endpoint

### Rosak (1 commits)

- **0ff57ec** [chore](rosak): refresh GraphQL schema snapshot for media fields

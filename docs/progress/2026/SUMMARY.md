# Yearly Summary - 2026

Total commits: 104

## Monthly Breakdown

### 2026-09 (32 commits)

#### Incident (17 commits)

- **67a830c** [feat](incident): complete insiden reporting backend
- **b9bd6fd** [feat](incident): add public publicSocialMediaLinks GraphQL query with line filter
- **1533846** [feat](incident): allow admin to fully edit SocialMediaLink before completion
- **990d89c** [feat](incident): expose status on CalendarIncidentScalar
- **f1b89ec** [fix](incident): coerce null details/title/brief to empty string for CalendarIncident
- **799ea77** [fix](incident): coerce null title to empty string for SocialMediaLink
- (uncommitted) [fix](incident): backfill legacy incident/chronology rows to LIVE in migrations 0015/0016
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

#### Operation (1 commits)

- **7c813fe** [feat](operation): per-line pulse fields and DataLoaders

#### Spotting (1 commits)

- **46cfde5** [fix](spotting): mount the firebase credential from the real home path

#### Common (7 commits)

- (this commit) [chore](common): seed same-hour status variety and more station-tagged reports
- (this commit) [chore](common): seed hundreds of varied reports across lines
- **010428c** [test](common): cover video pipeline and bounded cleanup
- **82addcc** [feat](common): support video in temporary media pipeline
- **a9f1067** [feat](common): hold AWAITING_REVIEW media from auto-conversion
- **511afaa** [feat](common): expose media caption/duration/type on MediaScalar
- **9ba0763** [feat](common): add caption/duration to Media and widen content_type
- **a531e51** [feat](common): add AWAITING_REVIEW temporary media status
- (uncommitted) [fix](common): disable boto3 trailer checksums for OCI S3-compat (aws-chunked 501)

#### Telegram (4 commits)

- **82e5c3f** [test](telegram): cover media upload + /approve
- **ed9c461** [feat](telegram): register media handler and /approve command
- **ea49424** [feat](telegram): add /approve for reviewed media
- **a82de20** [feat](telegram): auto-attach incoming photo/video to latest spotting

#### Ci (1 commits)

- **6fd0d1a** [fix](ci): publish full commit hash for version endpoint

#### Rosak (1 commits)

- **0ff57ec** [chore](rosak): refresh GraphQL schema snapshot for media fields

### 2026-08 (73 commits)

#### Incident (29 commits)

- **163f1d0** [feat](incident): Add ongoing filter to calendar incident queries
- **cc8451c** [test](incident): Provide required indicator in chronology test
- **1f0725e** [style](incident): Format migration files with ruff
- **0d21cab** [feat](incident): Accept line/vehicle/station tags on social media links
- **3f8adca** [test](incident): Scope e2e journey queue assertions to membership
- **b0cbbde** [test](incident): Add rate-limit integration test for the extraction chain
- **2b72466** [test](incident): Add end-to-end user-journey workflows through the real submit path
- **ec3e1f6** [test](incident): Fill Wave 5 unit-test gaps to 91% coverage
- **4694629** [feat](incident): Return created incident id from createCalendarIncident
- **7fd9e11** [feat](incident): Add submit mutation for DRAFT->PENDING_APPROVAL workflow
- ... and 19 more commits

#### Other (17 commits)

- **6c754d4** [other]: Rename CLAUDE.md to AGENTS.md
- **ed2eb0a** [other]: [pre-commit.ci] pre-commit autoupdate
- **7d3f6b0** [other]: Make imgur optional
- **f397a51** [other]: Add public profile data request capabilities
- **723bf34** [other]: Add jejak fallbacks
- **619b5e2** [other]: Add spotting_today date functionality
- **10bb30c** [other]: Add tests
- **09a253b** [other]: Pass dategroup to get_trends function
- **5c0ad7f** [other]: Add tests
- **185def0** [other]: Add mcp servers
- ... and 7 more commits

#### Docs (6 commits)

- **2af0092** [docs](APPS): update feature readiness and known defects after 2026-08-24 fixes
- **bbfc3b8** [docs]: commit at logical checkpoints for a clear chronological history
- **308fcd1** [docs]: Require AI co-author attribution in commits
- **0e1f1f8** [docs]: Document calendar incident system, GraphQL API, and test gates
- **c9303e2** [docs]: Update CLAUDE.md and APPS.md for Strawberry GraphQL migration
- **5210b9c** [docs]: Add Strawberry GraphQL migration guide

#### Graphql (4 commits)

- **b427663** [refactor](graphql): Migrate filter decorators, connection types, and view config to modern Strawberry API
- **8c0eff5** [refactor](graphql): Migrate Phase 3 complex mutations and filters from UNSET to Maybe[T]
- **129eb13** [refactor](graphql): Migrate Phase 2 resolvers and intermediate inputs from UNSET to Maybe[T]
- **bb1e519** [refactor](graphql): Migrate Phase 1 leaf inputs and utils from UNSET to Maybe[T]

#### Common (3 commits)

- **8284a8d** [test](common): use TestCase for spotting_data_public migration test
- **1e2a421** [fix](common): re-enable NSFW moderation in upload pipeline
- **40e5801** [fix](common): resolve public_user by firebase uid

#### Deps (3 commits)

- **8d18688** [fix](deps): Vendor advanced_filters migrations for BigAutoField
- **5f68f6a** [eps]: Update dependencies
- **b324856** [deps]: Update to django 5.2

#### Fix (3 commits)

- **cb0e6fd** [fix]: Event mutation bugs
- **d941268** [fix]: /version not displaying proper hashes
- **66a5cf8** [fix]: Telegram bot token crashing entire app

#### Test (2 commits)

- **5be2677** [test](schema): Regenerate GraphQL snapshot baseline to match current schema
- **7e4cb86** [test]: Add schema snapshot baseline and Maybe[T] test utilities

#### Feat (2 commits)

- **fe64d5b** [feat]: Make more apps optional
- **89dc701** [feat]: Add jejak capabilities

#### Dev (2 commits)

- **b82c15b** [dev]: Fix migrations
- **c318fd4** [dev]: Add basic tests to prepare for django 5

#### Telegram_Provider (1 commits)

- **0d1c3a4** [feat](telegram_provider): single governed egress path for outbound messaging

#### Ci (1 commits)

- **00a95c6** [fix](ci): Add ruff to dev dependencies for test workflow


## Key Milestones (2026)

### Major Features & Refactors

- **2026-09-23** (this commit) [docs](incident): `LineStatusHourBucket.statusCounts` documented as reusing the existing `operation.schema.scalars.PassengerStatusCount` type (the feature itself landed in `22baa99`)
- **2026-09-22** (this commit) [fix](incident): `lineStatusHistory` returns the full 24-bucket service day (03:00 → 02:00) instead of stopping at the current hour; a line with no report still returns `[]` for the "No data" state
- **2026-09-22** (this commit) [chore](common): `seed_demo_data` generates hundreds of varied reports from a ~150-user pool (seeded RNG, delete-then-recreate idempotency, guaranteed multi-status lines inside the pulse window)
- **2026-09-22** (this commit) [feat](incident): public feed service-day filter (`currentServiceDayOnly`) plus cursor-independent `totalCount` on `SocialMediaLinkConnection`, and `LineStatusReportScalar.stations`
- **2026-09-22** (this commit) [feat](incident): per-status report breakdown on a line — `Line.passengerStatusCounts` exposes how many reports fell into each `PassengerStatus`, batched through the existing `line_pulse_loader`
- **2026-09-22** (a9418c5) [feat](incident): community front page backend — feed link submit with canonical-URL dedup + auto-upvote, line status reports, deterministic per-line passenger-status pulse (`operation.Line.passengerStatus`/`pulseLinks`) and social-link votes
- **2026-09-12** (a82de20) [feat](telegram): auto-attach incoming photo/video to latest spotting
- **2026-09-16** (uncommitted) [feat](telegram): /spotting_today not-in-service exclusion flag; media uploads queued as TemporaryMedia even while uploads disabled; /approve approves replied /link
- **2026-09-12** (82addcc) [feat](common): support video in temporary media pipeline
- **2026-09-16** (uncommitted) [feat](incident): submitter SocialMediaLink edit — admin lands LIVE, submitter forced back to PENDING_APPROVAL; omitted `incident_id` preserves association (Task 24)
- **2026-08-25** (8284a8d) [test](common): use TestCase for spotting_data_public migration test
- **2026-08-25** (0d1c3a4) [feat](telegram_provider): single governed egress path for outbound messaging
- **2026-08-24** (1e2a421) [fix](common): re-enable NSFW moderation in upload pipeline
- **2026-08-24** (163f1d0) [feat](incident): Add ongoing filter to calendar incident queries
- **2026-08-24** (5be2677) [test](schema): Regenerate GraphQL snapshot baseline to match current schema
- **2026-08-24** (cc8451c) [test](incident): Provide required indicator in chronology test
- **2026-08-24** (8d18688) [fix](deps): Vendor advanced_filters migrations for BigAutoField
- **2026-08-24** (1f0725e) [style](incident): Format migration files with ruff
- **2026-08-22** (0d21cab) [feat](incident): Accept line/vehicle/station tags on social media links
- **2026-08-22** (3f8adca) [test](incident): Scope e2e journey queue assertions to membership
- **2026-08-22** (0e1f1f8) [docs]: Document calendar incident system, GraphQL API, and test gates
- **2026-08-22** (b0cbbde) [test](incident): Add rate-limit integration test for the extraction chain
- **2026-08-22** (2b72466) [test](incident): Add end-to-end user-journey workflows through the real submit path
- **2026-08-22** (ec3e1f6) [test](incident): Fill Wave 5 unit-test gaps to 91% coverage
- **2026-08-22** (4694629) [feat](incident): Return created incident id from createCalendarIncident
- **2026-08-22** (7fd9e11) [feat](incident): Add submit mutation for DRAFT->PENDING_APPROVAL workflow
- **2026-08-22** (cdcb6e8) [fix](incident): Expose created on CalendarIncidentScalar
- **2026-08-22** (52fb3b4) [feat](incident): Expose CalendarIncidentCategory ids for the console filter
- **2026-08-22** (381a877) [feat](incident): Add admin-only console queue queries
- **2026-08-22** (c8f3776) [test](incident): Add end-to-end workflow integration tests

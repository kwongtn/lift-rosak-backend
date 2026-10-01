# Yearly Summary - 2026

Total commits: 115

## Monthly Breakdown

### 2026-10 (0 commits committed, 1 uncommitted)

#### Incident (1 commits)

- **(this commit)** [feat](incident): `publicSocialMediaLinks` — `lastWeekOnly` now EXCLUDES today by default, closed at local calendar midnight this morning so the default range is the half-open `[six days ago 00:00, today 00:00)` = the last six **completed** days; the new `displayTodayInLastWeek: Boolean! = false` drops the upper bound and restores the inclusive seven-day window and is inert when `lastWeekOnly` is `false`. The new `_event_window_before` is the upper-bound counterpart of `_event_window` (`occurred_at < bound & ~Q(pk__in=_in_window_subtree_roots(bound))` under collapse), reusing the same un-correlated recursive-CTE subquery so the two ends of the window stay the same question — a collapsed card is excluded when the ROOT **or any descendant at any depth** happened today, which the ordinary "root is the earliest link" grouping shape makes necessary. The cut is calendar midnight, deliberately **not** the 03:00 `service_day_start` rollover; `timezone.now()` is captured once so the two bounds cannot straddle a midnight; the exclusion runs before `totalCount`. No model change, no migration, `_event_window` / `_in_window_subtree_roots` byte-identical; SDL snapshot + argument list in `docs/components/incident.md`; 6 new flat tests + 5 new nested tests (2 pinned on the emitted SQL), with the 3 pre-existing tests whose fixtures needed today inside the window re-pointed at the inclusive form so both behaviours stay covered — **238** in `incident`, **225** across the feed/tree modules — see `docs/progress/2026/10/01.md`
- **(this commit)** [fix](incident): V1 review of that commit — no behaviour change; `currentServiceDayOnly + lastWeekOnly` **intersects** (empty from the 03:00 rollover until midnight) and needs `displayTodayInLastWeek: true`, now documented and pinned clock-independently (**239** in `incident`), and two `service_day_start`-anchored fixtures re-anchored to absolute wall time after the pre-fix one was reproduced failing at a frozen 00:05
- **(uncommitted)** [feat](incident): `SocialMediaLink` — the flat one-level thread became an **ordered nested tree** — `django-tree-queries>=0.26.1` (chosen over `django-treenode` because it stores nothing: `tree_path` is a per-query recursive-CTE annotation, so no redundant column, no in-memory tree, no signal on every `save()`); the `thread` self-FK becomes `parent` (`TreeNodeForeignKey`, `on_delete=SET_NULL` — the *opposite* of the library's hardcoded `CASCADE`, so deleting a link promotes its sublinks to roots) plus the sibling sequence `position` and `Meta.ordering = ["position"]`; migration `0031` is hand-ordered and reversible, its group conversion defensive (the dev DB holds 44 links and zero members) while the `Window(RowNumber())` rank backfill does real work; the library's loop protection is `clean()`-only so a plain `save()` wrote cycles **silently** (unreachable from the CTE anchor, `ancestors()` raising `DoesNotExist`) — the model now guards in `save()`; `services/social_link_threads.py` rewritten around **no cycles** and **depth ≤ 3**, both checked before any write, with `group` (a null `parentId` starts a conversation; a named one nests one level deeper), `ungroup` (not a cascade) and the new `reorder` (a permutation of one sibling set, not a move), positions assigned explicitly because re-parenting never recomputes them; GraphQL breaks the surface on purpose and **without aliases** — `threadId`/`threadSize`/`threadLinks` → `parentId`/`position`/`sublinkCount`/`sublinks` + `reorderSocialMediaLinks` — and one `sublink_subtrees` loader costs `1 + (rows with children)` queries instead of one per tree level, with the badge and the list both derived from that one fetch; `collapseThreads` → `parent__isnull`, `_event_window`'s correlated `EXISTS` → an un-correlated `pk__in` recursive-CTE subquery taking `tree_path[1]` (widening to any depth, moderation deliberately root-only), and `tree_filter` **rejected** because it orphans out-of-window roots and silently breaks the widening; 3 new test modules, **191 tests green by full dotted label** — see `docs/progress/2026/10/01.md`
- **(this commit)** [feat](incident): the nine vote mutations (link, incident, chronology × up/down/remove) acknowledge with `VoteMutationPayload` — `ok` retained plus `userVote`/`voteScore`/`upvotes`/`downvotes` — instead of a bare `ok`, because a client given only `ok` must project the new score itself and that projection races its own echo and every other voter; `services/votes.py` returns a `VoteOutcome` in one aggregate round-trip, all nine share one `_vote_payload`, the nine retypings are NAMED in `EXPECTED_ACCEPTED_BREAKING_CHANGES` (15) with a new `_CHANGED_TYPE` anti-rot shape, SDL snapshot regenerated — see `docs/progress/2026/10/01.md`


### 2026-09 (43 commits)

#### Incident (27 commits)

- (this commit) [feat](incident): `SocialMediaLink.occurred_at` + thread grouping — a new NOT NULL `occurred_at` (`default=timezone.now`) is the user-facing "when did this happen" instant, backfilled `COALESCE(posted_at, created)` by a single-SQL reversible migration `0030` behind composite index `socialmedialink_occurred_idx`; `posted_at` stays read-only provider provenance for `export_official_posts` and ingestion writes both; every social-link ordering/window/cursor (`get_public_social_media_links`, the console queue whose args are renamed `createdAfter`/`createdBefore` → `occurredAfter`/`occurredBefore` — a deliberate breaking GraphQL change, `batch_load_incident_links`, `CalendarIncidentScalar.links`) moves to `occurred_at`; a `thread` self-FK root with a service-enforced depth-1 invariant plus the `thread_members` loader, `threadId`/`isThreadRoot`/`threadSize`/`threadLinks`, `groupSocialMediaLinks`/`ungroupSocialMediaLinks` (admin any / submitter own, all-or-nothing) and `collapseThreads` on the feed, because client-side grouping is unsound under event-time ordering; 6 new test files + regenerated SDL snapshot — honest test numbers in `docs/progress/2026/09/30.md`

- (this commit) [feat](incident): `publicSocialMediaLinks` gains `lastWeekOnly` (today + previous six calendar days, `last_week_start`) and `alignPageToDay` (complete-day pages, no cap — a whole day lands on one page, `endCursor` at its last row, `hasNextPage` an existence probe; `totalCount` unchanged), args inferred from the resolver signature + regenerated schema snapshot; 8 tests
- (this commit) [fix](incident): decode HTML entities once at the ingest boundary — `html.unescape` in `tweet_to_raw_post`, the single mapping behind the poll, the fixture loader and the webhook parser, so both ingest paths store `&` instead of `&amp;`; `raw_payload` keeps the encoded original for export fidelity and a second decode would corrupt `&amp;amp;`; 8 new tests + a MISTAKES entry
- (this commit) [feat](incident): hide links from the public feed and expose `isAutomated` — `SocialMediaLinkStatus.HIDDEN` (migration `0028`, choices-only) as a moderation decision excluded unconditionally by `get_public_social_media_links` after the `status` narrowing, so an explicit `status: HIDDEN` returns an empty page; `mine` and the console queue are deliberately exempt; `isAutomated: Boolean!` on the link scalar for the "Official" badge; +11 tests and a regenerated schema snapshot
- (this commit) [fix](incident): read the X `includes` expansion from `data` — the receiver read the expansion at the top level, so every real `post.create` delivery resolved no handle and was counted `unresolved` (ingested path dead in production, tests green because the fixture shared the bug); new `_expansion_containers` searches the nested location first and falls back to the top level, the test helper now defaults to the real XAA envelope, +5 regression tests (nested resolves with no network, top-level fallback, nested-wins precedence, malformed shapes) and a MISTAKES entry
- (this commit) [feat](incident): receive X Activity API webhook deliveries — `GET/POST /webhooks/x-api` (CRC challenge, HMAC-SHA256 over raw bytes, `post.create` → `SocialMediaLink`, queued Telegram notification, idempotent on redelivery) + the `x_webhook` management command for registration/subscriptions; 70 new tests, + docs (attribution rules, env matrix, CRC troubleshooting) and a MISTAKES entry for the debug-toolbar/Redis-cache test traps
- (this commit) [feat](incident): official-post polling is opt-in — `OFFICIAL_POST_POLLING_ENABLED` (default off; webhook path is primary) gates both the beat entry (`official_post_polling_entry()`) and the task (`{"skipped": "polling_disabled"}`); all existing master-flag tests updated + `official_post_polling_entry()`/polling-disabled tests added
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
- **32b7686** [feat](incident): admin-only `deleteSocialMediaLink` mutation removes a feed link

#### Operation (1 commits)

- **7c813fe** [feat](operation): per-line pulse fields and DataLoaders
- (uncommitted) [fix](operation): exclude `calendar_incidents` from `LineAdmin` change form (slow page loaded every incident; field no longer required)

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

#### Telegram (5 commits)

- **82e5c3f** [test](telegram): cover media upload + /approve
- **ed9c461** [feat](telegram): register media handler and /approve command
- **ea49424** [feat](telegram): add /approve for reviewed media
- **a82de20** [feat](telegram): auto-attach incoming photo/video to latest spotting
- **6075118** [fix](telegram): `/spotting_today` referenced a non-existent `VehicleStatus` member — now excludes `OUT_OF_SERVICE`
- **42d8b12** [feat](telegram): `/spotting_today` service-day cutoff — 3am default (pre-3am counts as previous day), `--use-actual-date`, `--cutoff=HHMM`; explicit date never shifted

#### Ci (1 commits)

- **6fd0d1a** [fix](ci): publish full commit hash for version endpoint

#### Rosak (1 commits)

- **0ff57ec** [chore](rosak): refresh GraphQL schema snapshot for media fields

#### Python (1 commits)

- **bc45bf1** [chore](python): upgrade runtime to Python 3.13

#### Compose (1 commits)

- **2acbbc2** [fix](compose): mount firebase credentials into celerybeat

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

- **2026-10-01** (uncommitted) [feat](incident): social-link threads become an **ordered nested tree** — `SocialMediaLink` inherits `tree_queries.OrderableTreeNode` and the flat `thread` self-FK becomes `parent` + the sibling sequence `position` under migration `0031` (hand-ordered, reversible, group conversion defensive); `save()` carries the cycle guard the library only puts in `clean()`; `services/social_link_threads.py` enforces no-cycles and depth <= 3 and gains `reorderSocialMediaLinks`; the scalar publishes `parentId`/`isThreadRoot`/`position`/`sublinkCount`/`sublinks` and one `sublink_subtrees` loader replaces `thread_members`, so a page costs `1 + (rows with children)` queries and the count and the list are the same read; `collapseThreads` narrows to roots and `_event_window` widens the window to the whole subtree via an un-correlated recursive-CTE subquery while moderation stays root-only. `threadId`/`threadSize`/`threadLinks` and `group`'s `threadId` were removed **without aliases** on purpose, and the breaking delta is named in the snapshot gate
- **2026-09-30** (this commit) [feat](incident): social links gain an explicit event datetime and thread grouping — `SocialMediaLink.occurred_at` (NOT NULL, backfilled `COALESCE(posted_at, created)` in migration `0030`, indexed `(-occurred_at, -id)`) becomes the "when did this happen" instant every ordering/window/cursor reads, with `posted_at` retained as read-only provider provenance; `SocialMediaLink.thread` is a self-FK whose root represents the group (depth-1 invariant enforced by the new `services/social_link_threads.py`), surfaced as `threadId`/`isThreadRoot`/`threadSize`/`threadLinks`, written by `groupSocialMediaLinks`/`ungroupSocialMediaLinks`, and paginated by a new `collapseThreads` feed argument; console queue filters renamed `createdAfter`/`createdBefore` → `occurredAfter`/`occurredBefore` (deliberate breaking change)
- **2026-09-28** (this commit) [feat](incident): official-post polling made explicitly opt-in — `OFFICIAL_POST_POLLING_ENABLED` (env, default `false`) gates the beat entry via the importable `official_post_polling_entry()` helper and hard-stops the task with `{"skipped": "polling_disabled"}`; the webhook receiver (separate follow-up) is the primary path
- **2026-09-26** (this commit) [feat](incident): official-post dataset export — `export_official_posts` streams the `is_automated=True` rows to JSONL/CSV (`--handle/--since/--until/--format/--output/--include-raw/--dry-run/--push-to-hub`) in a stable `posted_at, post_id, id` order, with an optional lazy-imported private HuggingFace push; 367-test full suite OK
- **2026-09-26** (this commit) [feat](incident): scheduled official-post ingestion — `incident.tasks.ingest_official_posts` on a 5-minute beat (`expires` 240 / `time_limit` 180), the `ingest_official_posts` management command for backfill (`--handle/--since/--until/--limit/--fixture/--dry-run`), and 5 test classes; 323-test full suite OK
- **2026-09-26** **c23e7bc** [feat](incident): official post ingestion foundation — `IngestPlatform` + `SocialMediaLink` ingestion fields with a partial unique constraint on `(platform, post_id)`, the bounded `services/official_posts.py` X API client, and the `system:official-ingest` service user
- **2026-09-24** **6a8f25e** [fix](rosak): `has_admin_claim` returns False (deny) when Firebase reports `UserNotFoundError`, instead of 500ing `IsAdmin` and the 12 conditional-admin resolvers
- **2026-09-24** **51f2f69** [test]: the 7 pre-existing failures no longer reach the live Firebase Admin API; 5 `telegram_provider.LinkHandlerTests` patch `rosak.permissions.has_admin_claim` (function-local import) and 2 `incident.SocialMediaLinkTests` patch `incident.schema.mutations.interactions.has_admin_claim` (module-level import)
- **2026-09-24** **fc72187** [chore](deps): pinned dependencies refreshed; `pendulum` 3.0.0 to 3.2.0 (now a cp313 wheel) with 15 further same-major bumps, `redis` held at 5.2.1
- **2026-09-24** **bc45bf1** [chore](python): runtime upgraded to Python 3.13 (base image + `requires-python` pins, plus a `rosak/test_python_runtime.py` guard that fails the gate on a silent downgrade)
- **2026-09-24** **2acbbc2** [fix](compose): celerybeat re-declares the firebase credential mount its explicit `volumes:` list had dropped (it crash-looped with `ImproperlyConfigured` on recreation)
- **2026-09-24** (uncommitted) [fix](operation): `LineAdmin` excludes the `calendar_incidents` M2M — the change form no longer loads every CalendarIncident, and the field is no longer required
- **2026-09-24** **42d8b12** [feat](telegram): `/spotting_today` service-day cutoff — pre-3am counts as the previous day by default; `--use-actual-date` (12am) and `--cutoff=HHMM` override; explicit dates never shift
- **2026-09-24** **6075118** [fix](telegram): `/spotting_today` excludes the operation status `OUT_OF_SERVICE` — the not-in-service flag referenced a non-existent `VehicleStatus.NOT_IN_SERVICE`, so every digest call raised `AttributeError`
- **2026-09-23** **32b7686** [feat](incident): admin-only `deleteSocialMediaLink` mutation removes a feed link (the ownership check in `delete_social_media_link` is bypassed for admins)
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

- **2026-09-28** (uncommitted, production core) [feat](incident): `Agency` + `SocMedAccount` registry — the DB becomes the single source of truth for tracked accounts (`OFFICIAL_POST_HANDLES` removed from settings); migration 0029 seeds Prasarana/Unassigned and askrapidkl/myrapidkl with baked user payloads; `SocialMediaLink` moves from denormalized `platform`/`source_handle` to a nullable `socmed_account` FK with a `(socmed_account, post_id)` partial unique constraint; `resolve_account`/`ensure_user_profile`/`sync_account_profiles` replace the handle→id cache; webhook attribution uses the registry `(_users_by_id`/`_resolve_account)`. Follow-up agents rewire tests/tasks/management commands (suite red by design).
- **2026-09-28** (uncommitted, consumer rewiring) [feat](incident): `ingest_official_posts` polls the enabled X `SocMedAccount` registry (`_ingest_account(SocMedAccount)` → `fetch_user_posts(account, since_id=latest_post_id(account))`; empty registry → uniform zero-totals dict), notification text reads `link.socmed_account.handle` via `select_related`, the ingest/export commands resolve handles through the registry (fixture dry-run writes nothing incl. accounts; export `handle` column from the FK, null → `""`), and `x_webhook subscribe` uses `resolve_account`+`ensure_user_profile`. `ruff`/`check`/`makemigrations --check` clean; dev-DB smoke passed. Tests red by design (follow-up agent).
- **2026-09-28** (registry feature shipped) [feat](incident): the Agency/SocMedAccount registry feature is **committed end-to-end** — production core + consumers + migration 0029 + fully-rewired tests (incident **223 tests**, full suite **483 tests**, all OK) + docs. Test rewrite adds registry seed/behaviour suites, `is_enabled` poll gating (only enabled accounts fetched), empty-registry zero-totals shape, `_users_by_id` full-object webhook attribution with seeded-id AAA/subscribe paths, one-bounded-sweep retry, and a dry-run guard against unregistered `--handle`s; removes the last `OFFICIAL_POST_HANDLES` / cached-reverse-lookup / `source_handle` test seams.

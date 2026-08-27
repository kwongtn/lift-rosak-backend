# Monthly Summary - August 2026

Total commits: 73

## Commit Type Distribution

- feat: 20
- other: 17
- test: 10
- fix: 9
- docs: 6
- refactor: 5
- dev: 2
- style: 1
- eps: 1
- chore: 1
- deps: 1

## By Module/Feature

### Incident (29 commits)

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
- **cdcb6e8** [fix](incident): Expose created on CalendarIncidentScalar
- **52fb3b4** [feat](incident): Expose CalendarIncidentCategory ids for the console filter
- **381a877** [feat](incident): Add admin-only console queue queries
- **c8f3776** [test](incident): Add end-to-end workflow integration tests
- **971d845** [feat](incident): Expose vote_score, vote_breakdown, and user_vote on incident GraphQL types
- **14ffc86** [feat](incident): Wire GenericRelation votes onto CalendarIncident and chronologies
- **7e5f372** [chore](incident): Drop stale services_pkg/_old.py rename placeholder
- **f6e4da8** [refactor](incident): Split services and mutation resolvers by aggregate
- **8e44216** [feat](incident): Add Celery purge tasks for expired incidents
- **b9ae9c3** [feat](incident): Add extractDataFromUrl mutation proxying Firebase Function
- **d55aeb8** [feat](incident): Add social media link mutations
- **457243f** [feat](incident): Add upvote/downvote/remove_vote mutations
- **7dc96d2** [feat](incident): Add chronology CRUD and reorder mutations
- **b25b1d4** [feat](incident): Add CalendarIncident CRUD mutations with status workflow and OCC
- **5a363b8** [feat](incident): Add GraphQL input types for incident mutations
- **017e3d2** [fix](incident): Point Vote/SocialMediaLink user FKs at common.User and adopt pytest
- **3f39d73** [test](incident): Add GenericFK wiring tests for SocialMediaLink
- **1f3a1da** [feat](incident): Add soft delete, audit history, status workflow, and Vote DataLoaders
- **ef87a25** [feat](incident): Add Vote model, SocialMediaLink model, and CalendarIncidentStatus enum

### Other (17 commits)

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
- **1f82abc** [other]: Add gitignore
- **0cf0ceb** [other]: WIP on main: eb04dcd Fix migration imports
- **2982068** [other]: index on main: eb04dcd Fix migration imports
- **63a9c03** [other]: untracked files on main: eb04dcd Fix migration imports
- **eb04dcd** [other]: Fix migration imports
- **ed3ae0a** [other]: Add docs
- **fab9b3b** [other]: Update dependencies

### Docs (6 commits)

- **2af0092** [docs](APPS): update feature readiness and known defects after 2026-08-24 fixes
- **bbfc3b8** [docs]: commit at logical checkpoints for a clear chronological history
- **308fcd1** [docs]: Require AI co-author attribution in commits
- **0e1f1f8** [docs]: Document calendar incident system, GraphQL API, and test gates
- **c9303e2** [docs]: Update CLAUDE.md and APPS.md for Strawberry GraphQL migration
- **5210b9c** [docs]: Add Strawberry GraphQL migration guide

### Graphql (4 commits)

- **b427663** [refactor](graphql): Migrate filter decorators, connection types, and view config to modern Strawberry API
- **8c0eff5** [refactor](graphql): Migrate Phase 3 complex mutations and filters from UNSET to Maybe[T]
- **129eb13** [refactor](graphql): Migrate Phase 2 resolvers and intermediate inputs from UNSET to Maybe[T]
- **bb1e519** [refactor](graphql): Migrate Phase 1 leaf inputs and utils from UNSET to Maybe[T]

### Common (3 commits)

- **8284a8d** [test](common): use TestCase for spotting_data_public migration test
- **1e2a421** [fix](common): re-enable NSFW moderation in upload pipeline
- **40e5801** [fix](common): resolve public_user by firebase uid

### Deps (3 commits)

- **8d18688** [fix](deps): Vendor advanced_filters migrations for BigAutoField
- **5f68f6a** [eps]: Update dependencies
- **b324856** [deps]: Update to django 5.2

### Fix (3 commits)

- **cb0e6fd** [fix]: Event mutation bugs
- **d941268** [fix]: /version not displaying proper hashes
- **66a5cf8** [fix]: Telegram bot token crashing entire app

### Test (2 commits)

- **5be2677** [test](schema): Regenerate GraphQL snapshot baseline to match current schema
- **7e4cb86** [test]: Add schema snapshot baseline and Maybe[T] test utilities

### Feat (2 commits)

- **fe64d5b** [feat]: Make more apps optional
- **89dc701** [feat]: Add jejak capabilities

### Dev (2 commits)

- **b82c15b** [dev]: Fix migrations
- **c318fd4** [dev]: Add basic tests to prepare for django 5

### Telegram_Provider (1 commits)

- **0d1c3a4** [feat](telegram_provider): single governed egress path for outbound messaging

### Ci (1 commits)

- **00a95c6** [fix](ci): Add ruff to dev dependencies for test workflow

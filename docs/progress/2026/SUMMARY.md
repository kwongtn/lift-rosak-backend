# Yearly Summary - 2026

Total commits: 73

## Monthly Breakdown

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

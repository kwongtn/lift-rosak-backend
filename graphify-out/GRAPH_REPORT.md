# Graph Report - rosak_backend  (2026-10-08)

## Corpus Check
- 427 files · ~264,784 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 17 file(s) not represented in the graph (top: (none) 7, .ini 2, .template 2)

## Summary
- 4446 nodes · 12656 edges · 255 communities (151 shown, 104 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 1988 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8dff111a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- services/__init__.py
- LocationFilter
- RangeAbstractModel
- extract_data_from_url
- import_range_utils.py
- VehicleStatus
- Vehicle
- operation/schema/schema.py
- TimescaleRouterTests
- incident/admin.py
- ImgurStorage
- GenericMutationReturn
- test_console_queries.py
- _Info
- send_message
- TemporaryMediaConversionTaskTests
- strawberry
- SocialMediaLinkScalar
- SpottingEventType
- operation/tests.py
- SocialMediaLink
- mcp
- Django 4.2/5.2 web framework (backend core)
- handlers.py
- reporting/admin.py
- Media
- CalendarIncident
- common/utils.py
- execute_graphql_async
- Vote
- raise_service_error
- .date
- test_mutation_resolvers.py
- typing
- telegram_provider.utils.send_message
- LineAdmin
- LinkHandlerTests
- common/tests.py
- imgur_storage.py
- execute_graphql
- User
- test_severity_count_resolver.py
- GracefulDegradationGraphQLTests
- UserScalar
- SocMedAccount
- official_posts.py
- SpottingMutations
- rosak/urls.py
- test_incident_mutations.py
- GHCR Build and Push Workflow
- incident/tests.py
- django_db_models_deletion
- ingest_posts
- XWebhookCommandTests
- test_unit_gaps.py
- TestCase
- telegram_provider/tests.py
- RosakSchemaTests
- error_handler
- common/models.py
- test_page_title.py
- test_integration_workflows.py
- test_vote_mutations.py
- TreeCycleGuardTests
- django_contrib
- Query
- parsers.py
- CalendarIncidentStatus
- incident/schema/resolvers.py
- SocialMediaLinkWrite
- SocialMediaLinkTests
- ._reorder
- ._group
- _link
- OperationGraphQLTests
- CalendarIncidentChronologyTests
- test_social_media_link_mutations.py
- TemporaryMedia → Discord CDN → Media staged state machine
- Event vehicle sighting ledger aggregate root
- operation.Asset
- test_incident_edit_semantics.py
- canonicalize_url
- TestSchemaSnapshot
- CalendarIncident network-level disruption span
- Line
- WebLocationModel abstract GIS model
- LineReliabilityScore
- generic/types.py
- PublicFeedLastWeekAndDayAlignTests
- CI Test Workflow
- CommonConfig
- Report crowd-sourced asset defect report
- 2026-09-22
- Semaphore Deploy Pipeline
- strawberry.Maybe[T] tri-state UNSET/Some(value)/Some(None)
- django_apps
- ._link
- Redis cache and Celery broker
- Snapshot daily point-in-time per line status counts
- Badge community award model
- spot
- XWebhookDeliveryViewTests
- 0005_alter_calendarincident_severity.py
- incident/tasks.py
- load_network_status_history
- override_settings
- EventFilter
- _parent_of
- 0005_vehicleline_many_to_many_data.py
- service_day_start
- get_public_social_media_links
- Dependabot Docker Updates
- OfficialPostNotificationTests
- django_db
- _link
- PassengerStatus
- test_social_link_feed_ordering.py
- test_line_pulse_loaders.py
- approve
- media
- test_line_status_history.py
- IngestOfficialPostsCommandTests
- VehicleType
- test_feed_link_submit.py
- get_daily_updates
- votes.py
- ExportOfficialPostsCommandTests
- spotting/models.py
- dev_permissioner.sh
- Granian ASGI app service
- get_trends date-bucketing analytics engine
- decode_keyset_cursor
- spotting/migrations/0001_initial.py
- Command
- xaa_post_create_payload
- test_my_votes_cast.py
- test_incident_history.py
- test_scalar_fields.py
- bucket_hourly
- EventCheckConstraintTests
- test_feed_link_mutations.py
- test_social_link_scalar_votes.py
- ThreadGroupingMutationTests
- load_lines_status_history
- 0015_calendarincident_deleted_and_more.py
- ._feed
- django_choices_field_fields
- LastWeekTodayExclusionTests
- test_social_link_votes.py
- LoaderBatchingTests
- LinkHierarchyTestCase
- test_extraction.py
- .links
- By Module/Feature
- ExportOfficialPostsHubPushTests
- models/views.py
- pytest
- GitVersionViewTests
- test_line_status_report_model.py
- test_line_status_reports.py
- Any
- 0031_socialmedialink_tree_parent_and_more.py
- batch_load_sublink_subtrees
- PublicFeedHiddenGateTests
- XWebhookCrcViewTests
- ConsoleQueueOrderingTests
- OccurredAtBackfillTests
- _event_window
- run_celery.sh
- run_celery_beat.sh
- HasAdminClaimTests
- retry_on_error
- PositionCostsNoQueryTests
- DepthCapTests
- LockOrderTests
- test_line_status_report_submit.py
- FeedLinkOccurredAtTests
- Component: {COMPONENT_NAME}
- 0030_socialmedialink_occurred_at_socialmedialink_thread_and_more.py
- ConsoleQueueHiddenFilterTests
- PublicFeedApprovalGateTests
- PublicFeedContractTests
- LegacyStatusBackfillTests
- ._feed_capture
- AutoApproveOfficialLinksBackfillTests
- CountAndListAgreeTests
- SublinkCountTests
- System Component Registry & Architecture Map
- Pre-commit Hooks
- Celery beat central schedule in rosak/celery.py with six jobs
- Firebase bearer-token auth with lazy get_or_create common.User
- PostGIS GeoDjango geometry fields
- Single async GraphQL endpoint
- Progress Log - 2026-09-12
- By Module/Feature
- BigAutoField default and advanced_filters.0004 migration
- Django 5.2.17 upgrade from 4.2.20
- TimescaleDB service timescale/timescaledb-ha:pg16
- rosak project schema assembly context permissions beat schedule
- SourceCustomLine vocabulary reconciliation via explicit through
- Insiden approved and pending approval card sections
- 2026-08-26: Rename CLAUDE.md to AGENTS.md (1 commit)
- DjangoListConnection replacing ListConnectionWithTotalCount
- Filter decorator migration strawberry_django.filters.filter to filter
- interactions.py
- x_webhooks.py
- jejak/tests.py
- markAsRead gated IsAdmin blocking per-user read state
- StationIncident UniqueConstraint missing condition Q(is_last=True)
- 0032_autoapprove_official_links.py
- rosak-backend
- GraphQL calendarIncidents and incident mutations API
- reporting/schema/scalars.py
- GracefulDegradationSettingsTests
- _AsyncIterable
- execute_graphql
- 2026-09-23
- _row_fields
- SoftDeleteOrderedQueryset
- SoftDeleteOrderedManager
- PythonRuntimeTests
- ExecutorRoundTripTests
- get_criteria
- Progress — 2026-10-03

## God Nodes (most connected - your core abstractions)
1. `User` - 269 edges
2. `SocialMediaLink` - 203 edges
3. `_Info` - 126 edges
4. `CalendarIncident` - 119 edges
5. `Line` - 104 edges
6. `CalendarIncidentStatus` - 99 edges
7. `PassengerStatus` - 86 edges
8. `Vehicle` - 60 edges
9. `SocialMediaLinkStatus` - 56 edges
10. `IncidentServiceError` - 53 edges

## Surprising Connections (you probably didn't know these)
- `Incident: admin-only `deleteSocialMediaLink` mutation` --references--> `SocialMediaLinkMutations`  [INFERRED]
  docs/progress/2026/09/23.md → incident/schema/mutations/interactions.py
- `[2026-10-03] tests: freezing `django.utils.timezone.now` does NOT freeze `auto_now_add`` --references--> `service_day_start()`  [INFERRED]
  docs/progress/2026/10/03.md → incident/services/line_status.py
- `Telegram (5 commits)` --references--> `VehicleStatus`  [INFERRED]
  docs/progress/2026/09/SUMMARY.md → operation/enums.py
- `Incident: `statusCounts` docs — name the reused type` --references--> `PassengerStatusCount`  [INFERRED]
  docs/progress/2026/09/23.md → operation/schema/scalars.py
- `Python: upgrade runtime to 3.13` --references--> `LinkHandlerTests`  [INFERRED]
  docs/progress/2026/09/24.md → telegram_provider/tests.py

## Import Cycles
- 4-file cycle: `common/imgur_storage.py -> common/tasks.py -> incident/models.py -> common/models.py -> common/imgur_storage.py`

## Hyperedges (group relationships)
- **Canary Progressive Delivery Flow** — _k8s_charts_templates_app_canary_flagger_canary, _k8s_charts_templates_app_deployment_app_deployment, _k8s_charts_templates_app_hpa_hpa, _k8s_charts_templates_app_canary_analysis [EXTRACTED 1.00]
- **Docker Compose stack nginx granian PostGIS Redis Celery worker and beat** — docker_compose_nginx_web, docker_compose_granian_app, docker_compose_postgis_db, docker_compose_timescaledb, docker_compose_redis, docker_compose_celeryworker, docker_compose_celerybeat [EXTRACTED 1.00]
- **Nine Django apps plus rosak project forming MLPTF community platform** — docs_apps_operation, docs_apps_common, docs_apps_spotting, docs_apps_incident, docs_apps_chartography, docs_apps_telegram_provider, docs_apps_generic, docs_apps_reporting, docs_apps_mlptf, docs_apps_rosak_project [EXTRACTED 1.00]
- **Strawberry GraphQL 0.243 to 0.323 Maybe pattern migration across six waves** — docs_strawberry_migration_maybe, docs_strawberry_migration_filter_decorator, docs_strawberry_migration_connection, agents_strawberry_maybe, django_5_2_upgrade_strfilterlookup [EXTRACTED 1.00]
- **CI/CD Image Pipeline** — _github_workflows_push_image_ghcr_ghcr_build_push, _k8s_charts_values_helm_values, _github_workflows_cleanup_image_retention_policy [INFERRED 0.85]

## Communities (255 total, 104 thin omitted)

### Community 0 - "services/__init__.py"
Cohesion: 0.09
Nodes (34): CalendarIncidentChronology, get_incident(), is_author(), may_edit(), approve_chronology(), approve_chronology_deletion(), _chronology_with_parent(), ChronologyUpdate (+26 more)

### Community 1 - "LocationFilter"
Cohesion: 0.07
Nodes (5): LocationFilter, JejakIndexAndQueryPlanTests, JejakLocationsCountTests, TestFilterDecorators, TestLocationResolvers

### Community 2 - "RangeAbstractModel"
Cohesion: 0.08
Nodes (32): Migration, ForeignKeyCompositeIdentifierDetailAbstractModel, IdentifierDetailAbstractModel, Meta, RangeAbstractModel, Accessibility, AccessibilityBusRange, Bus (+24 more)

### Community 3 - "extract_data_from_url"
Cohesion: 0.12
Nodes (10): extract_data_from_url(), ExtractionError, _Context, test_extract_resolver_translates_extraction_error(), failing_extract(), _SimulatedFirebaseFunction, test_every_proxied_call_forwards_the_callers_token(), test_limit_is_per_user_not_global() (+2 more)

### Community 4 - "import_range_utils.py"
Cohesion: 0.14
Nodes (14): reconnect(), wrap_errors(), aggregate_start_end_dt(), get_field_name(), get_fk_df(), group_is_close_dt(), instance_mapping_fn(), multi_fk_range_import() (+6 more)

### Community 5 - "VehicleStatus"
Cohesion: 0.09
Nodes (20): LineVehicleStatusCountHistoryAdmin, LineVehicleStatusCountHistoryTabularInline, SnapshotAdmin, SourceAdmin, SourceCustomLineAdmin, DataSources, Migration, LineVehicleStatusCountHistory (+12 more)

### Community 6 - "Vehicle"
Cohesion: 0.06
Nodes (21): TestUserScalarTrends, VehicleIncident, IncidentModelTests, Vehicle, batch_load_incident_count_from_vehicle(), batch_load_incident_from_vehicle(), batch_load_last_spotting_date_from_vehicle_id(), batch_load_spotting_count_from_vehicle() (+13 more)

### Community 7 - "operation/schema/schema.py"
Cohesion: 0.13
Nodes (14): IncidentAbstractFilter, StationIncidentFilter, VehicleIncidentFilter, AssetFilter, LineFilter, StationFilter, StationLineFilter, VehicleFilter (+6 more)

### Community 9 - "incident/admin.py"
Cohesion: 0.06
Nodes (23): GeometricForm, Meta, AgencyAdmin, CalendarIncidentAdmin, CalendarIncidentAdminForm, CalendarIncidentCategoryAdmin, CalendarIncidentChronologyAdmin, CalendarIncidentChronologyInlineAdmin (+15 more)

### Community 11 - "GenericMutationReturn"
Cohesion: 0.26
Nodes (3): GenericMutationReturn, ChronologyMutations, has_admin_claim()

### Community 12 - "test_console_queries.py"
Cohesion: 0.23
Nodes (13): CalendarIncidentCategory, get_calendar_incident_categories(), get_social_media_links(), _make_pending(), _make_user(), test_categories_query_lists_all_ordered_by_name(), test_pending_incidents_excludes_other_statuses(), test_pending_incidents_includes_live_with_pending_deletion_chronologies() (+5 more)

### Community 13 - "_Info"
Cohesion: 0.10
Nodes (7): Line, Vehicle, VehicleStatusCount, VehicleType, LineVehicleSpottingTrend, VehicleSpottingTrend, _Info

### Community 14 - "send_message"
Cohesion: 0.17
Nodes (7): Incident: official-post Phase 2 — admin notification, reply approval, and the public-feed gate, SendMessageTests, get_ptb_application(), _json_serializable_kwargs(), _outbound_message_payload(), send_message(), TelegramBotNotReady

### Community 15 - "TemporaryMediaConversionTaskTests"
Cohesion: 0.09
Nodes (9): FeatureFlagType, add_data(), Migration, FeatureFlag, CleanupExpiredVerificationCodesTaskTests, CleanupTemporaryMediaTaskTests, SpottingDataPublicMigrationTests, TemporaryMediaConversionTaskTests (+1 more)

### Community 16 - "strawberry"
Cohesion: 0.08
Nodes (12): TestUserInput, WebLocationInput, GenericPrimitivesTests, TestWebLocationInput, assert_maybe_field_behavior(), execute_graphql(), get_graphql_context(), RosakSchemaExecutionTests (+4 more)

### Community 17 - "SocialMediaLinkScalar"
Cohesion: 0.13
Nodes (6): CalendarIncidentChronologyScalar, CalendarIncidentScalar, _content_type_id(), SocialMediaLinkScalar, _visible_subtree(), VoteBreakdown

### Community 18 - "SpottingEventType"
Cohesion: 0.31
Nodes (7): SpottingDataSource, SpottingEventType, fix_stations(), Migration, add_spotting_event_source(), add_spotting_event_source_to_event(), Migration

### Community 19 - "operation/tests.py"
Cohesion: 0.08
Nodes (30): AssetAdmin, AssetMediaStackedInline, AssetMediaTabluarInline, AssetStackedInline, AssetTabularInline, LineStackedInline, StationForm, StationLineStackedInline (+22 more)

### Community 20 - "SocialMediaLink"
Cohesion: 0.05
Nodes (40): Incident: PassengerStatus, LineStatusReport, and canonicalized social-link URLs, Incident: `SocialMediaLink` — flat one-level thread → ordered nested tree, Incident (1 commits), CalendarIncidentChronologyIndicator, CalendarIncidentSeverity, IncidentSeverity, SocialMediaLinkStatus, IncidentAbstractModel (+32 more)

### Community 21 - "mcp"
Cohesion: 0.10
Nodes (20): command, enabled, type, GITHUB_PERSONAL_ACCESS_TOKEN, command, enabled, environment, type (+12 more)

### Community 22 - "Django 4.2/5.2 web framework (backend core)"
Cohesion: 0.08
Nodes (28): 2026-08-06: Update dependencies (Other, fab9b3b), 2026-08-14: Add docs (ed3ae0a), 2026-08-17: Fix migration imports and MCP servers (6 commits), 2026-08-18: Django 5.2 upgrade, Jejak capabilities, Telegram fix (10 commits), 2026-08-19: Strawberry GraphQL Maybe[T] 4-phase migration and docs (11 commits), 2026-08-21: Incident Vote, SocialMediaLink, CalendarIncidentStatus core models (4 commits), 2026-08-22: Incident feature wave 25 commits - CRUD, voting, Celery purge, submit workflow, 2026-08-24: Fixes (NSFW, public_user, advanced_filters) and incident filter/docs (12 commits) (+20 more)

### Community 23 - "handlers.py"
Cohesion: 0.12
Nodes (15): SpottingWheelStatus, EventSource, ASGILifespanSignalHandler, HTTPXAppConfig, TelegramProviderConfig, dad_joke(), delete(), delete_link() (+7 more)

### Community 24 - "reporting/admin.py"
Cohesion: 0.13
Nodes (16): ReportAdmin, ReportMediaStackedInline, ReportResolutionStackedInline, ReportStackedInline, ResolutionAdmin, ResolutionStackedInline, VoteAdmin, VoteStackedInline (+8 more)

### Community 25 - "Media"
Cohesion: 0.09
Nodes (16): ClearanceAdmin, FeatureFlagAdmin, MediaAdmin, MediaStackedInline, MediaTabularInline, TemporaryMediaAdmin, UserAdmin, UserClearanceStackedInline (+8 more)

### Community 26 - "CalendarIncident"
Cohesion: 0.12
Nodes (22): Incident, Progress Log - 2026-09-13, Compose: celerybeat lost the firebase credential mount, CalendarIncident, get_pending_calendar_incidents(), purge_rejected_incidents(), purge_soft_deleted_incidents(), CalendarIncidentExtensionsTests (+14 more)

### Community 27 - "common/utils.py"
Cohesion: 0.07
Nodes (14): CreditType, UserJejakTransactionCategory, UserJejakTransaction, TestDateUtilities, get_charge_credits_objs(), get_combinations(), get_default_start_time(), get_group_strs() (+6 more)

### Community 28 - "execute_graphql_async"
Cohesion: 0.06
Nodes (8): CommonGraphQLTests, TestDjangoListConnection, TestUpdateUserMutation, UserPrivacyTests, [2026-10-01] common: month-boundary fixture in `test_get_user_data_query_profile_aggregates`, execute_graphql_async(), SpottingGraphQLTests, TestAddEventMutation

### Community 29 - "Vote"
Cohesion: 0.17
Nodes (12): Meta, Vote, batch_load_user_vote_value(), batch_load_vote_breakdown(), batch_load_vote_scores(), _cast_vote(), _content_type(), _make_incident() (+4 more)

### Community 30 - "raise_service_error"
Cohesion: 0.17
Nodes (7): [2026-10-01] incident: vote mutations acknowledge with the vote state, not a bare `ok`, SocialMediaLinkMutations, _vote_payload(), VoteMutations, raise_service_error(), VoteMutationPayload, IncidentMutations

### Community 31 - ".date"
Cohesion: 0.09
Nodes (9): CalendarIncidentDateFilter, CalendarIncidentFilter, DateRangeInput, IntExactInput, TestCalendarIncidentFilter, spotting_today(), EffectiveSpottingDateTests, SpottingTodayHandlerTests (+1 more)

### Community 32 - "test_mutation_resolvers.py"
Cohesion: 0.18
Nodes (22): IncidentCrudMutations, _incident_input(), _make_user(), no_admin_claim(), _service_write(), strawberry_id(), test_approve_resolver_promotes_pending(), test_chronology_resolvers_crud_and_reorder() (+14 more)

### Community 33 - "typing"
Cohesion: 0.11
Nodes (12): TriggerInput, ChartographyMutations, ChartographyScalars, MediaOrder, MediaScalar, Incident: submitter edit of SocialMediaLink — role rule + forced re-approval (Task 24), IsAdmin, IsLoggedIn (+4 more)

### Community 34 - "telegram_provider.utils.send_message"
Cohesion: 0.10
Nodes (21): BoundedRetry, DeadLetterQueue, spotting.tasks.report_spotting_today, telegram_provider.utils.send_message, settings.TELEGRAM_ADMIN_CHAT_ID, telegram_provider.models.TelegramLogs, DigestFormat, spotting.EventRead (+13 more)

### Community 35 - "LineAdmin"
Cohesion: 0.38
Nodes (5): Operation: Line admin loaded every CalendarIncident (slow change form), Operation (1 commits), LineAdmin, StationLineAdmin, LineAdminConfigTests

### Community 36 - "LinkHandlerTests"
Cohesion: 0.22
Nodes (4): Test: fix the 7 pre-existing failures (Firebase admin check mocked), submit_link(), spotting_today_parser(), LinkHandlerTests

### Community 37 - "common/tests.py"
Cohesion: 0.10
Nodes (22): ClearanceType, TemporaryMediaStatus, TemporaryMediaType, add_clearance(), Migration, Clearance, TemporaryMedia, UserClearance (+14 more)

### Community 38 - "imgur_storage.py"
Cohesion: 0.08
Nodes (9): ImgurClient, ImgurImageFieldFile, Command, add_dimensions(), Migration, Migration, Migration, Migration (+1 more)

### Community 39 - "execute_graphql"
Cohesion: 0.13
Nodes (4): execute_graphql(), IncidentSchemaExecutionTests, SocialMediaLinkTests, TestCalendarIncidentResolvers

### Community 40 - "User"
Cohesion: 0.05
Nodes (33): User, FeedLinkValidationError, IncidentServiceError, LineStatusValidationError, _acquire_canonical_lock(), _advisory_lock_key(), _attach_line_reports(), _canonical_exists() (+25 more)

### Community 41 - "test_severity_count_resolver.py"
Cohesion: 0.25
Nodes (9): get_calendar_incidents_by_severity_count(), GroupByEnum, _make_incident(), _start_of(), test_day_grouping_counts_long_and_short_term(), test_interval_clamps_to_requested_window(), test_missing_dates_raise_graphql_error(), test_month_grouping_counts_by_severity() (+1 more)

### Community 42 - "GracefulDegradationGraphQLTests"
Cohesion: 0.29
Nodes (3): execute_graphql(), get_graphql_context(), GracefulDegradationGraphQLTests

### Community 43 - "UserScalar"
Cohesion: 0.09
Nodes (13): UserInput, MediasGroupByPeriodScalar, MediaType, UserScalar, UserVerificationCodeScalar, CommonMutations, CommonScalars, FavouriteVehicleData (+5 more)

### Community 44 - "SocMedAccount"
Cohesion: 0.05
Nodes (21): [2026-09-28] incident: Agency + SocMedAccount registry (production core, no commit), [2026-09-28] incident: tests rewired to the Agency/SocMedAccount registry (commit), Registry feature shipped (1 commits), Test (1 commits), IngestPlatform, Agency, SocMedAccount, ensure_user_profile() (+13 more)

### Community 45 - "official_posts.py"
Cohesion: 0.06
Nodes (20): 2026-09-26, Docs: record the ingestion surface and a new trap, Incident: official post ingestion foundation (Phase 1, part 1), Incident: scheduled ingestion task, backfill command and tests (Phase 1, part 2), Incident: post text is HTML-entity decoded once, at the ingest boundary, Command, OfficialPostFetchError, OfficialPostIngestError (+12 more)

### Community 46 - "SpottingMutations"
Cohesion: 0.12
Nodes (6): DeleteEventInput, MarkEventAsReadInput, EventScalar, LocationEvent, _maybe_value(), SpottingMutations

### Community 47 - "rosak/urls.py"
Cohesion: 0.06
Nodes (3): FirebaseUser, CustomGraphQLView, TestGraphQLViewConfig

### Community 48 - "test_incident_mutations.py"
Cohesion: 0.43
Nodes (13): _make_user(), test_admin_creates_live(), test_approve_merges_draft_to_parent(), test_approve_requires_pending_for_non_revision(), test_delete_rules(), test_optimistic_concurrency_control(), test_reject_records_reason_and_status(), test_submit_missing_incident_raises() (+5 more)

### Community 49 - "GHCR Build and Push Workflow"
Cohesion: 0.15
Nodes (14): Container Retention Policy, Scheduled GHCR Cleanup Workflow, Docker Buildx Multi-Arch Build, GHCR Build and Push Workflow, Git Metadata Tagging, Helm Chart Backend, Canary Analysis Metrics, Flagger Canary Deployment (+6 more)

### Community 50 - "incident/tests.py"
Cohesion: 0.05
Nodes (8): AutoApproveOfficialLinksBackfillTests, ExportOfficialPostsFixture, main(), ReportingMutations, ReportingScalars, debug_task(), PYTHONPATH, run_app.sh script

### Community 51 - "django_db_models_deletion"
Cohesion: 0.04
Nodes (31): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+23 more)

### Community 52 - "ingest_posts"
Cohesion: 0.05
Nodes (13): Incident: `SocialMediaLink.occurred_at` — an explicit event datetime, [2026-10-08] incident: official posts auto-publish (`LIVE`) + console `hidden` filter, Progress — 2026-10-08, get_system_author(), ingest_posts(), _Unset, OfficialPostAutoPublicationTests, OfficialPostIngestTests (+5 more)

### Community 53 - "XWebhookCommandTests"
Cohesion: 0.10
Nodes (3): Command, fake_x_response(), XWebhookCommandTests

### Community 54 - "test_unit_gaps.py"
Cohesion: 0.28
Nodes (11): CalendarIncidentMedia, batch_load_medias_from_calendar_incident(), _make_user(), test_admin_can_submit_any_draft(), test_medias_loader_groups_by_incident_and_defaults_empty(), test_model_str_and_admin_widget_render(), test_non_json_response_raises_extraction_error(), test_reject_live_incident_raises() (+3 more)

### Community 55 - "TestCase"
Cohesion: 0.11
Nodes (6): Incident: official-post polling is now opt-in (webhook path is primary), LineStatusReportStationsTests, OfficialPostPollingDisabledTests, OfficialPostPollingEntryTests, TestFilterDecorators, official_post_polling_entry()

### Community 56 - "telegram_provider/tests.py"
Cohesion: 0.09
Nodes (8): MessageDirection, TelegramLogs, cleanup_telegram_logs(), CleanupTelegramLogsTaskTests, PerChatRateLimiterTests, TelegramProviderModelTests, PerChatRateLimiter, TelegramInbound

### Community 59 - "common/models.py"
Cohesion: 0.11
Nodes (6): ImgurField, Migration, Migration, MediaMixin, batch_load_media_from_id(), batch_load_spottings_from_user()

### Community 60 - "test_page_title.py"
Cohesion: 0.09
Nodes (17): Incident: feed-link submit and line-status-report services, fetch_page_title(), _is_public_host(), _stub_dns(), test_blocks_ssrf_targets_without_any_request(), test_does_not_follow_redirects(), test_parses_unescapes_and_collapses_title(), handler() (+9 more)

### Community 61 - "test_integration_workflows.py"
Cohesion: 0.42
Nodes (10): _backdate(), _make_user(), test_edit_live_merge_preserves_votes(), test_full_lifecycle_draft_to_live_to_soft_deleted(), test_rejected_purge_after_30_days(), test_soft_delete_purge_after_90_days_cascades_votes(), test_submit_approve_upvote_workflow(), _upvote() (+2 more)

### Community 62 - "test_vote_mutations.py"
Cohesion: 0.32
Nodes (17): _chronology_content_type(), _incident_content_type(), _make_chronology(), _make_incident(), _make_user(), test_chronology_downvote_creates_vote(), test_chronology_remove_vote(), test_chronology_upvote_changes_downvote() (+9 more)

### Community 63 - "TreeCycleGuardTests"
Cohesion: 0.06
Nodes (5): _link(), TreeCycleGuardTests, TreeDeletePromotionTests, TreeModelShapeTests, TreePositionTests

### Community 64 - "django_contrib"
Cohesion: 0.10
Nodes (6): JsonPrettifyAdminMixin, BusAdmin, BusTypeAdmin, LocationAdmin, LocationPaginator, TelegramLogAdmin

### Community 65 - "Query"
Cohesion: 0.36
Nodes (7): Mutation, Query, _build_schema(), _field_names(), test_incident_input_and_enum_types_are_in_schema(), test_root_mutation_exposes_all_incident_mutations(), test_root_query_exposes_incident_fields()

### Community 66 - "parsers.py"
Cohesion: 0.15
Nodes (5): ArgumentParser, Formatter, link_parser(), _parse_cutoff(), spotting_parser()

### Community 67 - "CalendarIncidentStatus"
Cohesion: 0.35
Nodes (21): CalendarIncidentStatus, _chronology_write(), _make_incident(), _make_user(), test_approve_chronology_deletion_soft_deletes(), test_chronology_cannot_be_approved_if_parent_not_live(), test_chronology_inherits_parent_status_on_creation(), test_chronology_reorder() (+13 more)

### Community 68 - "incident/schema/resolvers.py"
Cohesion: 0.12
Nodes (25): Source, CalendarIncidentOrder, get_calendar_incident_history(), get_line_status_history(), get_line_status_reports(), get_lines_status_history(), get_network_status_history(), _hour_bucket() (+17 more)

### Community 69 - "SocialMediaLinkWrite"
Cohesion: 0.09
Nodes (7): SocialMediaLinkWrite, execute_graphql(), _link(), OccurredAtMutationTriStateTests, PublicVisibilityTests, SubmitOccurredAtTests, UpdateOccurredAtTests

### Community 71 - "._reorder"
Cohesion: 0.09
Nodes (7): execute_graphql(), PositionFieldTestCase, PositionNullabilityTests, ReorderRoundTripTests, SiblingPositionTests, social_link_scalar_block(), ReorderTests

### Community 72 - "._group"
Cohesion: 0.10
Nodes (5): AtomicityTests, CycleRejectionTests, GroupInputValidationTests, GroupPermissionTests, _tree()

### Community 73 - "_link"
Cohesion: 0.09
Nodes (8): historical_apps_at_0031_data_migration(), legacy_thread_column(), LegacyThreadTestCase, _link(), PositionBackfillTests, _positions_by_pk(), ReverseMigrationTests, ThreadGroupConversionTests

### Community 74 - "OperationGraphQLTests"
Cohesion: 0.13
Nodes (4): execute_graphql(), OperationGraphQLTests, PassengerStatusCountsGraphQLTests, TestFilterDecorators

### Community 76 - "test_social_media_link_mutations.py"
Cohesion: 0.24
Nodes (15): _make_incident(), _make_user(), test_admin_resolver_filters(), test_admin_resolver_hidden_tri_state_filter(), test_mark_social_media_link_completed_records_admin_user(), test_submit_social_media_link_description_round_trip(), test_submit_social_media_link_status_defaulting(), test_submit_social_media_link_title_null_and_omitted_coerce_to_empty() (+7 more)

### Community 77 - "TemporaryMedia → Discord CDN → Media staged state machine"
Cohesion: 0.29
Nodes (7): tach.yml cross-app import boundaries, common app identity media analytics substrate, TemporaryMedia → Discord CDN → Media staged state machine, PTB Application ASGI lifespan webhook registration, ImgurStorage on hot path for every Media creation, infinite_retry_on_error unbounded retry pinning worker, NSFW moderation bypass all uploads convert unchecked

### Community 78 - "Event vehicle sighting ledger aggregate root"
Cohesion: 0.29
Nodes (7): spotting app sighting ledger, telegram_provider app Telegram bridge, Vehicle rolling-stock with VehicleStatus, Event vehicle sighting ledger aggregate root, spotting_parser argparse grammar for /spot command, TelegramLogs raw payload audit log with MessageDirection, get_daily_updates overwrites spotting_date with date.today

### Community 79 - "operation.Asset"
Cohesion: 0.29
Nodes (7): batch_load_assets_from_station DataLoader, AssetStatusEnum, operation.Asset, reporting.Report, reporting.Vote, StationAccessibility, incident.StationIncident

### Community 80 - "test_incident_edit_semantics.py"
Cohesion: 0.19
Nodes (24): _make_media(), _make_user(), test_admin_can_delete_any_incident(), test_admin_in_place_update_preserves_pending_approval(), test_admin_in_place_update_preserves_pending_deletion(), test_admin_in_place_update_still_version_checked(), test_admin_update_edited_content_loses_pending_deletion_flag(), test_admin_updates_live_in_place() (+16 more)

### Community 81 - "canonicalize_url"
Cohesion: 0.06
Nodes (32): backfill_normalized_urls(), Migration, Migration, rebackfill_normalized_urls(), canonicalize_url(), filter_transactions(), strtobool(), test_alias_subdomain_strip_is_case_insensitive() (+24 more)

### Community 83 - "CalendarIncident network-level disruption span"
Cohesion: 0.33
Nodes (6): incident app disruption record, operation app reference-data hub, CalendarIncident network-level disruption span, Line canonical transit line reference, Dual Line ↔ CalendarIncident join tables permanently empty GraphQL field, Calendar incident DRAFT→PENDING_APPROVAL→LIVE/REJECTED workflow

### Community 84 - "Line"
Cohesion: 0.11
Nodes (6): Command, add(), SeedDemoDataCommandTests, Common: same-hour status variety and station-tagged demo reports, Line, test_same_hour_slots_guarantee_distinct_statuses()

### Community 85 - "WebLocationModel abstract GIS model"
Cohesion: 0.40
Nodes (5): PostGIS db service postgis/postgis:17-3.5-alpine, generic app table-less shared kernel, GeometricForm lat/long admin widget, WebLocationModel abstract GIS model, LocationEvent GPS payload extending WebLocationModel

### Community 86 - "LineReliabilityScore"
Cohesion: 0.40
Nodes (5): CalendarIncident.impact_factor, compute_line_reliability_scores, LineReliabilityScore, ReliabilityTrend, suggested_impact_factor

### Community 87 - "generic/types.py"
Cohesion: 0.70
Nodes (3): GeometricSearchField, Point2D, Point2D_SearchField

### Community 89 - "CI Test Workflow"
Cohesion: 0.50
Nodes (4): CI Test Workflow, Django Verification Gate, Ruff Lint and Format Gate, Ruff Pre-commit Hook

### Community 91 - "Report crowd-sourced asset defect report"
Cohesion: 0.50
Nodes (4): reporting app asset defects dormant, Asset lift escalator station asset, Report crowd-sourced asset defect report, Vote corroboration with ballot stuffing gap

### Community 92 - "2026-09-22"
Cohesion: 0.11
Nodes (11): 2026-09-22, Common: high-volume varied demo seed, Incident: deterministic line-status consolidation, Incident: line-status history covers the whole service day, Incident: per-status breakdown on each hourly history bucket, Operation: per-line pulse fields and DataLoaders, Spotting: Firebase credential mount points at the real home path, Traps discovered (+3 more)

### Community 93 - "Semaphore Deploy Pipeline"
Cohesion: 0.67
Nodes (3): Semaphore Deploy Pipeline, Sentry Release Process, Semaphore Legacy Docker Pipeline

### Community 94 - "strawberry.Maybe[T] tri-state UNSET/Some(value)/Some(None)"
Cohesion: 0.67
Nodes (3): strawberry.Maybe[T] tri-state optional inputs, StrFilterLookup replacing FilterLookup[str] for DuplicatedTypeName fix, strawberry.Maybe[T] tri-state UNSET/Some(value)/Some(None)

### Community 95 - "django_apps"
Cohesion: 0.09
Nodes (7): ChartographyConfig, GenericConfig, IncidentConfig, JejakConfig, MlptfConfig, OperationConfig, ReportingConfig

### Community 96 - "._link"
Cohesion: 0.15
Nodes (4): OccurredAtFieldTests, ParentIdAndRootMarkerTests, SublinkOrderingTests, VisibilityGatingTests

### Community 97 - "Redis cache and Celery broker"
Cohesion: 0.67
Nodes (3): Celery beat service, Celery worker service, Redis cache and Celery broker

### Community 98 - "Snapshot daily point-in-time per line status counts"
Cohesion: 0.67
Nodes (3): chartography app time-series ledger, Snapshot daily point-in-time per line status counts, impact_factor reliability deduction score

### Community 99 - "Badge community award model"
Cohesion: 0.67
Nodes (3): mlptf app badges, Badge community award model, UserBadge through-model award relation

### Community 100 - "spot"
Cohesion: 0.20
Nodes (7): Telegram Provider: `/spot` vehicle matching — exact match key after space normalisation, Telegram Provider (1 commit), normalize_vehicle_number(), spot(), vehicle_number_match_key(), SpotHandlerTests, VehicleNumberMatchKeyTests

### Community 101 - "XWebhookDeliveryViewTests"
Cohesion: 0.13
Nodes (3): aaa_post_create_payload(), signed_delivery(), XWebhookDeliveryViewTests

### Community 103 - "incident/tasks.py"
Cohesion: 0.10
Nodes (10): 2026-09-28, [2026-09-28] incident: consumer rewiring to the Agency/SocMedAccount registry (uncommitted), Incident: `HIDDEN` link status + `isAutomated` on the link scalar, _build_notification_text(), _format_posted_at(), _notify_created_links(), _notify_new_link(), notify_official_post_links() (+2 more)

### Community 104 - "load_network_status_history"
Cohesion: 0.13
Nodes (4): load_network_status_history(), NetworkStatusHistoryTests, ServiceDayHistoryFixtureMixin, StatusHistoryQueryTests

### Community 105 - "override_settings"
Cohesion: 0.20
Nodes (4): crc_response_token(), sign_body(), verify_webhook_signature(), XWebhookSigningTests

### Community 106 - "EventFilter"
Cohesion: 0.12
Nodes (3): EventFilter, ReportSpottingTodayTaskTests, TestFilterDecorators

### Community 107 - "_parent_of"
Cohesion: 0.13
Nodes (5): _assert_well_formed(), NestingTests, NewThreadTests, _parent_of(), UngroupTests

### Community 109 - "service_day_start"
Cohesion: 0.13
Nodes (7): 2026-10-01, [2026-10-01] Incident: V1 review fixes (clock-proof fixtures, combined-window decision), [2026-10-01] verification gate, Incident: `publicSocialMediaLinks` — `lastWeekOnly` excludes today (`displayTodayInLastWeek`), last_week_start(), service_day_start(), FeedWindowTests

### Community 111 - "get_public_social_media_links"
Cohesion: 0.25
Nodes (6): get_public_social_media_links(), _Ctx, _FakeInfo, _ids(), _make_link(), PublicSocialMediaLinkTests

### Community 113 - "OfficialPostNotificationTests"
Cohesion: 0.16
Nodes (3): fake_sender(), NotifyOfficialPostLinksTaskTests, OfficialPostNotificationTests

### Community 114 - "django_db"
Cohesion: 0.03
Nodes (32): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+24 more)

### Community 115 - "_link"
Cohesion: 0.17
Nodes (6): _assert_numbered(), _child_ids(), _children(), _link(), OrderingTests, _positions()

### Community 116 - "PassengerStatus"
Cohesion: 0.25
Nodes (20): Operation: per-status report breakdown on Line, PassengerStatus, consolidate(), Consolidation, _entry(), test_below_min_reports_returns_none(), test_default_window_is_fifteen_minutes(), test_empty_entries_returns_none() (+12 more)

### Community 117 - "test_social_link_feed_ordering.py"
Cohesion: 0.15
Nodes (5): AlignPageToDayTests, FeedKeysetPaginationTests, FeedOrderingTests, LegacyCursorTests, SocialLinkFeedOrderingBase

### Community 118 - "test_line_pulse_loaders.py"
Cohesion: 0.23
Nodes (19): VehicleLine, batch_load_line_pulse(), batch_load_line_vehicle_counts(), _assign(), _counts(), _make_line(), _make_report(), _make_user() (+11 more)

### Community 119 - "approve"
Cohesion: 0.26
Nodes (4): Telegram: /approve on a replied /link message approves the link, approve(), TelegramSocialMediaLinkLog, ApproveHandlerTests

### Community 120 - "media"
Cohesion: 0.31
Nodes (3): Telegram: media uploads always record a TemporaryMedia row, even while uploads disabled, media(), MediaHandlerTests

### Community 121 - "test_line_status_history.py"
Cohesion: 0.26
Nodes (16): [2026-10-03] incident: network + multi-line service-day status history (B1, B2), HourBucket, load_line_status_history(), _build_schema(), _context(), _make_line(), _make_report(), _make_user() (+8 more)

### Community 123 - "VehicleType"
Cohesion: 0.18
Nodes (15): VehicleType, reference(), _assign(), _build_schema(), _context(), _execute(), _line(), _make_line() (+7 more)

### Community 124 - "test_feed_link_submit.py"
Cohesion: 0.26
Nodes (17): _link_count_for(), _make_line(), _make_station(), _make_user(), test_blank_title_fetches_page_title(), fake_fetch(), test_different_canonical_urls_create_two_rows(), test_duplicate_by_tracking_params_dedups_and_upvotes() (+9 more)

### Community 125 - "get_daily_updates"
Cohesion: 0.13
Nodes (12): 2026-09-16, Telegram: /spotting_today excludes not-in-service by default, `--include-not-in-service`/`--inis` opt-in, 2026-09-24, Deps: refresh pinned dependencies (pendulum 3.2 + 15 same-major bumps), Python: upgrade runtime to 3.13, Rosak: has_admin_claim no longer 500s when the Firebase account is missing, Telegram: `/spotting_today` referenced a non-existent `VehicleStatus` member, Telegram: `/spotting_today` service-day cutoff (3am default) (+4 more)

### Community 126 - "votes.py"
Cohesion: 0.26
Nodes (15): Incident: social-link votes and the feed status filter, _aggregate_votes(), _apply_vote(), _content_type_for(), _get_chronology(), _get_social_media_link(), remove_chronology_vote(), remove_incident_vote() (+7 more)

### Community 128 - "spotting/models.py"
Cohesion: 0.18
Nodes (11): Meta, WebLocationModel, EventMedia, EventRead, LocationEvent, Meta, batch_load_is_read_from_event(), batch_load_location_event_from_event() (+3 more)

### Community 132 - "decode_keyset_cursor"
Cohesion: 0.24
Nodes (5): decode_keyset_cursor(), encode_keyset_cursor(), CalendarIncidentLinksTests, _make_incident(), _make_incident_link()

### Community 133 - "spotting/migrations/0001_initial.py"
Cohesion: 0.14
Nodes (5): Migration, Migration, Migration, Migration, Migration

### Community 135 - "xaa_post_create_payload"
Cohesion: 0.25
Nodes (3): Incident: webhook read `includes` from the wrong level — every real delivery was dropped, xaa_post_create_payload(), XWebhookHandleResolutionTests

### Community 136 - "test_my_votes_cast.py"
Cohesion: 0.30
Nodes (12): _build_schema(), _content_type(), _context(), _execute(), _make_chronology(), _make_incident(), _make_user(), test_my_votes_cast_anonymous_rejected() (+4 more)

### Community 137 - "test_incident_history.py"
Cohesion: 0.46
Nodes (13): _build_schema(), _context(), _execute(), _history_query(), _make_incident(), _make_user(), test_actor_mapping_auth_user_username(), test_actor_null_when_system_makes_change() (+5 more)

### Community 138 - "test_scalar_fields.py"
Cohesion: 0.40
Nodes (13): _build_schema(), _context(), _execute(), _make_incident(), _make_user(), test_calendar_incident_scalar_author_null_when_no_created_by(), test_calendar_incident_scalar_exposes_author_short_id(), test_calendar_incident_scalar_exposes_version() (+5 more)

### Community 139 - "bucket_hourly"
Cohesion: 0.29
Nodes (10): bucket_hourly(), ReportEntry, _entry(), test_dominant_status_is_the_most_frequent(), test_dominant_status_tie_breaks_on_severity_rank(), test_no_reports_yields_empty_list(), test_report_at_exactly_day_start_belongs_to_first_bucket(), test_report_before_day_start_is_excluded() (+2 more)

### Community 141 - "test_feed_link_mutations.py"
Cohesion: 0.33
Nodes (12): _build_schema(), _context(), _execute(), _link_node(), _make_line(), _make_user(), test_duplicate_submit_returns_indicator_and_upvotes_without_new_row(), test_status_without_line_ids_raises_graphql_error() (+4 more)

### Community 142 - "test_social_link_scalar_votes.py"
Cohesion: 0.41
Nodes (12): _build_schema(), _cast_vote(), _context(), _links(), _make_link(), _make_user(), _node(), test_normalized_url_exposed_and_matches_model() (+4 more)

### Community 144 - "load_lines_status_history"
Cohesion: 0.22
Nodes (3): LineHistory, load_lines_status_history(), LinesStatusHistoryTests

### Community 145 - "0015_calendarincident_deleted_and_more.py"
Cohesion: 0.15
Nodes (5): backfill_existing_incidents_live(), Migration, backfill_existing_chronologies_live(), Migration, Migration

### Community 147 - "django_choices_field_fields"
Cohesion: 0.08
Nodes (11): Migration, Migration, Migration, Migration, seed_system_author(), Migration, Migration, seed_registry() (+3 more)

### Community 149 - "test_social_link_votes.py"
Cohesion: 0.35
Nodes (10): _link_content_type(), _make_link(), _make_user(), test_missing_link_raises_service_error(), test_outcome_counts_every_voter_not_just_the_caller(), test_remove_deletes_vote(), test_set_creates_upvote(), test_set_updates_existing_vote_not_inserts() (+2 more)

### Community 151 - "LinkHierarchyTestCase"
Cohesion: 0.21
Nodes (3): FixtureUrlTests, LinkHierarchyTestCase, unique_url()

### Community 152 - "test_extraction.py"
Cohesion: 0.32
Nodes (6): test_function_error_envelope_raises_extraction_error(), test_proxies_to_firebase_function_and_returns_result(), handler(), test_unconfigured_endpoint_raises_extraction_error(), test_unreachable_service_raises_extraction_error(), _transport()

### Community 153 - ".links"
Cohesion: 0.20
Nodes (8): Incident: public feed service-day filter and cursor-independent totals, 2026-09-30, Incident: every social-link ordering, window and cursor moved to `occurred_at`, Incident: `publicSocialMediaLinks` — `lastWeekOnly` + `alignPageToDay`, Incident: `SocialMediaLink.thread` — thread grouping, Incident (27 commits), batch_load_incident_links(), SocialMediaLinkConnection

### Community 154 - "By Module/Feature"
Cohesion: 0.17
Nodes (11): By Module/Feature, Ci (1 commits), Commit Type Distribution, Common (7 commits), Compose (1 commits), Deps (1 commits), Monthly Summary - September 2026, Python (1 commits) (+3 more)

### Community 157 - "models/views.py"
Cohesion: 0.44
Nodes (11): AccessibilityBusRangeView, BusProviderRangeView, BusRouteRangeView, BusStopBusRangeView, BusView, CaptainBusRangeView, CaptainProviderRangeView, EngineStatusBusRangeView (+3 more)

### Community 158 - "pytest"
Cohesion: 0.32
Nodes (8): _build_schema(), _cast_vote(), _context(), _make_link(), _make_user(), _node(), test_vote_breakdown_counts_up_and_down(), test_vote_breakdown_zero_when_no_votes()

### Community 159 - "GitVersionViewTests"
Cohesion: 0.20
Nodes (4): git_version(), redirect_view(), sentry(), GitVersionViewTests

### Community 160 - "test_line_status_report_model.py"
Cohesion: 0.44
Nodes (9): _make_line(), _make_link(), _make_user(), test_backfill_populates_normalized_url(), test_line_status_report_creation(), test_line_status_report_link_related_name(), test_non_http_url_still_saves(), test_social_media_link_save_populates_normalized_url() (+1 more)

### Community 161 - "test_line_status_reports.py"
Cohesion: 0.41
Nodes (9): _build_schema(), _context(), _execute(), _make_line(), _make_report(), _make_user(), test_keyset_pagination_walks_two_pages_without_gaps(), test_reports_are_newest_first() (+1 more)

### Community 162 - "Any"
Cohesion: 0.27
Nodes (3): _csv_cell(), _drain(), _RecordWriter

### Community 163 - "0031_socialmedialink_tree_parent_and_more.py"
Cohesion: 0.24
Nodes (5): [2026-10-01] incident: migration 0031 aborted on threaded rows — deferred-FK events vs. the trailing DDL, convert_threads_to_tree(), flush_deferred_constraints(), Migration, revert_tree_to_threads()

### Community 169 - "_event_window"
Cohesion: 0.31
Nodes (3): _event_window(), _event_window_before(), _in_window_subtree_roots()

### Community 177 - "test_line_status_report_submit.py"
Cohesion: 0.43
Nodes (5): _make_line(), _make_station(), _make_user(), test_creates_link_less_report_with_stations(), test_unknown_line_raises_service_error()

### Community 179 - "Component: {COMPONENT_NAME}"
Cohesion: 0.29
Nodes (6): Component: {COMPONENT_NAME}, 🧩 Extension Points & Hooks, 🔌 Interface & Data Flow, ⚙️ Internal State & Logic, 💡 Potential AI Feature Opportunities, 📌 Purpose & Scope

### Community 180 - "0030_socialmedialink_occurred_at_socialmedialink_thread_and_more.py"
Cohesion: 0.29
Nodes (3): backfill_occurred_at(), Migration, revert_occurred_at_to_created()

### Community 184 - "LegacyStatusBackfillTests"
Cohesion: 0.48
Nodes (3): _create_chronology(), _create_incident(), LegacyStatusBackfillTests

### Community 189 - "System Component Registry & Architecture Map"
Cohesion: 0.40
Nodes (4): 📚 Component Catalog, 🎯 Cross-Component Feature Opportunities, 🗺️ High-Level System Topology, System Component Registry & Architecture Map

### Community 196 - "Progress Log - 2026-09-12"
Cohesion: 0.40
Nodes (4): Chore, Common, Progress Log - 2026-09-12, Telegram

### Community 199 - "By Module/Feature"
Cohesion: 0.40
Nodes (4): By Module/Feature, Commit Type Distribution, Common (1 commit), Monthly Summary - October 2026

### Community 215 - "interactions.py"
Cohesion: 0.13
Nodes (16): Incident: feed submit and line status report mutations, Rosak: SDL snapshot regeneration, CalendarIncidentChronologyInput, CalendarIncidentInput, ExtractDataInput, FeedLinkInput, LineStatusReportInput, SocialMediaLinkInput (+8 more)

### Community 218 - "x_webhooks.py"
Cohesion: 0.08
Nodes (13): Incident: X Activity API webhook receiver (primary official-post ingestion path), _create_items(), _expansion_containers(), has_signing_secret(), ingest_webhook_payload(), _preferred_signing_secret(), WebhookIngestResult, XWebhookEntityDecodingTests (+5 more)

### Community 219 - "jejak/tests.py"
Cohesion: 0.19
Nodes (7): BusOrder, LocationOrder, Bus, BusType, Location, JejakMutations, JejakScalars

### Community 232 - "reporting/schema/scalars.py"
Cohesion: 0.47
Nodes (3): Report, Resolution, Vote

### Community 245 - "2026-09-23"
Cohesion: 0.50
Nodes (3): 2026-09-23, Incident: admin-only `deleteSocialMediaLink` mutation, Incident: `statusCounts` docs — name the reused type

## Knowledge Gaps
- **266 isolated node(s):** `Migration`, `Migration`, `Migration`, `Migration`, `SourceAdmin` (+261 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1338 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **104 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `User` to `services/__init__.py`, `VehicleStatus`, `Vehicle`, `test_console_queries.py`, `TemporaryMediaConversionTaskTests`, `strawberry`, `operation/tests.py`, `SocialMediaLink`, `handlers.py`, `reporting/admin.py`, `Media`, `CalendarIncident`, `common/utils.py`, `execute_graphql_async`, `Vote`, `test_mutation_resolvers.py`, `LinkHandlerTests`, `common/tests.py`, `execute_graphql`, `UserScalar`, `SocMedAccount`, `official_posts.py`, `rosak/urls.py`, `test_incident_mutations.py`, `incident/tests.py`, `ingest_posts`, `test_unit_gaps.py`, `TestCase`, `common/models.py`, `test_integration_workflows.py`, `test_vote_mutations.py`, `TreeCycleGuardTests`, `CalendarIncidentStatus`, `SocialMediaLinkWrite`, `SocialMediaLinkTests`, `._reorder`, `._group`, `_link`, `OperationGraphQLTests`, `test_social_media_link_mutations.py`, `test_incident_edit_semantics.py`, `Line`, `PublicFeedLastWeekAndDayAlignTests`, `2026-09-22`, `spot`, `incident/tasks.py`, `load_network_status_history`, `_parent_of`, `get_public_social_media_links`, `_link`, `test_social_link_feed_ordering.py`, `test_line_pulse_loaders.py`, `approve`, `media`, `test_line_status_history.py`, `VehicleType`, `test_feed_link_submit.py`, `get_daily_updates`, `votes.py`, `decode_keyset_cursor`, `test_my_votes_cast.py`, `test_incident_history.py`, `test_scalar_fields.py`, `EventCheckConstraintTests`, `test_feed_link_mutations.py`, `test_social_link_scalar_votes.py`, `ThreadGroupingMutationTests`, `._feed`, `test_social_link_votes.py`, `LinkHierarchyTestCase`, `pytest`, `test_line_status_report_model.py`, `test_line_status_reports.py`, `PublicFeedHiddenGateTests`, `OccurredAtBackfillTests`, `DepthCapTests`, `LockOrderTests`, `test_line_status_report_submit.py`, `FeedLinkOccurredAtTests`, `ConsoleQueueHiddenFilterTests`, `PublicFeedApprovalGateTests`, `PublicFeedContractTests`, `AutoApproveOfficialLinksBackfillTests`, `ExecutorRoundTripTests`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **Why does `SocialMediaLink` connect `SocialMediaLink` to `decode_keyset_cursor`, `Command`, `xaa_post_create_payload`, `test_scalar_fields.py`, `test_console_queries.py`, `test_feed_link_mutations.py`, `test_social_link_scalar_votes.py`, `SocialMediaLinkScalar`, `._feed`, `test_social_link_votes.py`, `LinkHierarchyTestCase`, `.links`, `._records`, `Vote`, `pytest`, `test_line_status_report_model.py`, `test_mutation_resolvers.py`, `batch_load_sublink_subtrees`, `common/tests.py`, `PublicFeedHiddenGateTests`, `execute_graphql`, `User`, `_event_window`, `ConsoleQueueOrderingTests`, `OccurredAtBackfillTests`, `SocMedAccount`, `official_posts.py`, `incident/tests.py`, `FeedLinkOccurredAtTests`, `ingest_posts`, `ConsoleQueueHiddenFilterTests`, `PublicFeedApprovalGateTests`, `TestCase`, `PublicFeedContractTests`, `AutoApproveOfficialLinksBackfillTests`, `TreeCycleGuardTests`, `incident/schema/resolvers.py`, `SocialMediaLinkWrite`, `SocialMediaLinkTests`, `._reorder`, `._group`, `_link`, `test_social_media_link_mutations.py`, `Line`, `PublicFeedLastWeekAndDayAlignTests`, `x_webhooks.py`, `2026-09-22`, `._link`, `XWebhookDeliveryViewTests`, `incident/tasks.py`, `ExecutorRoundTripTests`, `_parent_of`, `service_day_start`, `get_public_social_media_links`, `OfficialPostNotificationTests`, `_link`, `test_social_link_feed_ordering.py`, `test_line_pulse_loaders.py`, `IngestOfficialPostsCommandTests`, `VehicleType`, `test_feed_link_submit.py`, `votes.py`, `ExportOfficialPostsCommandTests`?**
  _High betweenness centrality (0.123) - this node is a cross-community bridge._
- **Why does `_Info` connect `_Info` to `test_mutation_resolvers.py`, `typing`, `extract_data_from_url`, `incident/schema/resolvers.py`, `EventFilter`, `GenericMutationReturn`, `UserScalar`, `SpottingMutations`, `get_public_social_media_links`, `SocialMediaLinkScalar`, `interactions.py`, `.links`, `jejak/tests.py`, `raise_service_error`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 192 inferred relationships involving `User` (e.g. with `ChartographyModelTests` and `UserStackedInline`) actually correct?**
  _`User` has 192 INFERRED edges - model-reasoned connections that need verification._
- **Are the 148 inferred relationships involving `SocialMediaLink` (e.g. with `Command` and `SeedDemoDataCommandTests`) actually correct?**
  _`SocialMediaLink` has 148 INFERRED edges - model-reasoned connections that need verification._
- **Are the 84 inferred relationships involving `CalendarIncident` (e.g. with `Incident` and `Operation: Line admin loaded every CalendarIncident (slow change form)`) actually correct?**
  _`CalendarIncident` has 84 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Migration`, `Migration`, `Migration` to the rest of the system?**
  _266 weakly-connected nodes found - possible documentation gaps or missing edges._

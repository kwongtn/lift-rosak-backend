# Graph Report - rosak_backend  (2026-09-02)

## Corpus Check
- 364 files · ~103,918 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2114 nodes · 4376 edges · 244 communities (94 shown, 113 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 180 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Incident Domain Core
- Jejak Bus Data Schema
- Bus Range Abstract Models
- URL Extraction Service
- Operation DataLoaders & Imports
- Chartography Snapshots
- Async ORM Tests
- Operation GraphQL Filters
- Timescale DB Router
- Incident Admin & GIS Forms
- Imgur Media Storage
- Chronology Mutations
- Social Link Console Queries
- Line & Vehicle Resolvers
- Governed Egress Tests
- Common Task Tests
- Tri-State Input Tests
- Incident Scalars
- Spotting Enums & Migrations
- Operation Models & Migrations
- Incident Soft-Delete Models
- Dev Tooling Config
- Backend Progress Logs
- Telegram Handlers
- Reporting Admin
- Common Admin
- Incident Tasks & Workflows
- Trend Date Utilities
- Common GraphQL Tests
- Vote DataLoaders
- Incident Interaction Mutations
- Incident GraphQL Filters
- Mutation Resolver Tests
- Common Schema & Permissions
- Egress & Subscription Concepts
- Operation Admin
- Link Handler Tests
- TemporaryMedia Lifecycle
- Media Field Migrations
- Incident GraphQL Integration Tests
- Credit & Clearance Models
- Severity Count Tests
- Jejak Degradation Tests
- User Scalar Resolvers
- Operation Model Tests
- Spotting Trend Tests
- Event Scalars & Inputs
- GraphQL View Tests
- Incident Workflow Tests
- CI/CD & K8s Deploy
- Chartography Mutations
- Media Loaders
- Privacy Enforcement Tests
- Incident Write Services
- Incident Unit Gap Tests
- Incident Model Tests
- Telegram Provider Module
- Schema Assembly Tests
- Telegram Admin Notify Tests
- Media Mixin
- Common Scalars
- Incident Integration Tests
- Vote Mutation Tests
- Clearance Migrations
- Jejak Admin
- Schema Build Tests
- Telegram Link Parser
- Chronology Mutation Tests
- Shared Schema Types
- Per-Chat Rate Limiter
- Social Link Model Tests
- Upload API View
- Public User Queries
- Admin Prettify Mixins
- Operation GraphQL Tests
- Chronology Status Tests
- Social Link Mutation Tests
- Common App Constraints
- Spotting & Telegram Concepts
- Station Accessibility Feature
- Project Entrypoints
- Settings & Sentry
- Schema Snapshot Tests
- Incident Workflow Concepts
- Telegram Inbound View
- GIS Location Concepts
- Impact Factor Feature
- Geo Search Fields
- Spotting Today Tests
- CI Test Gates
- Common AppConfig
- Reporting Concepts
- Spotting AppConfig
- Semaphore Deploy
- Strawberry Maybe Pattern
- Chartography AppConfig
- Chartography Migrations
- Celery Services
- Chartography Concepts
- Badge Concepts
- Generic AppConfig
- Incident AppConfig
- Severity Migration
- SocialLink Migrations
- Jejak AppConfig
- manage.py Entrypoint
- Mlptf AppConfig
- Operation AppConfig
- VehicleLine Migration
- Reporting AppConfig
- ASGI Entrypoint
- App Run Script
- Dependabot Updates
- advanced_filters Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Chartography Migrations
- Django Migrations
- Django Migrations
- Common User Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- dev_permissioner.sh
- Web Stack Services
- Trend Concepts
- Incident Initial Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Jejak Initial Migration
- Django Migrations
- Django Migrations
- Mlptf Initial Migration
- Operation Initial Migration
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- wsgi.py
- run_celery.sh
- run_celery_beat.sh
- Spotting Initial Migration
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- serializers.py
- Telegram Initial Migration
- Django Migrations
- Django Migrations
- Django Migrations
- Django Migrations
- Pre-commit Hooks
- Celery beat central schedule in rosak/ce
- Firebase bearer-token auth with lazy get
- PostGIS GeoDjango geometry fields
- Single async GraphQL endpoint
- BigAutoField default and advanced_filter
- Django 5.2.17 upgrade from 4.2.20
- TimescaleDB service timescale/timescaled
- rosak project schema assembly context pe
- SourceCustomLine vocabulary reconciliati
- Insiden approved and pending approval ca
- 2026-08-26: Rename CLAUDE.md to AGENTS.m
- DjangoListConnection replacing ListConne
- Filter decorator migration strawberry_dj
- markAsRead gated IsAdmin blocking per-us
- StationIncident UniqueConstraint missing
- rosak-backend
- GraphQL calendarIncidents and incident m

## God Nodes (most connected - your core abstractions)
1. `_Info` - 82 edges
2. `User` - 72 edges
3. `CalendarIncident` - 51 edges
4. `execute_graphql_async()` - 34 edges
5. `RangeAbstractModel` - 28 edges
6. `GenericMutationReturn` - 27 edges
7. `LinkHandlerTests` - 24 edges
8. `UserScalar` - 21 edges
9. `IsLoggedIn` - 20 edges
10. `CalendarIncidentStatus` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Ruff Pre-commit Hook` --semantically_similar_to--> `Ruff Lint and Format Gate`  [INFERRED] [semantically similar]
  .pre-commit-config.yaml → .github/workflows/test.yml
- `Line` --uses--> `Source`  [INFERRED]
  operation/schema/scalars.py → chartography/schema/scalars.py
- `ChartographyMutations` --uses--> `IsAdmin`  [INFERRED]
  chartography/schema/schema.py → rosak/permissions.py
- `ChartographyMutations` --uses--> `IsLoggedIn`  [INFERRED]
  chartography/schema/schema.py → rosak/permissions.py
- `UserScalar` --uses--> `IsAdmin`  [INFERRED]
  common/schema/scalars.py → rosak/permissions.py

## Import Cycles
- 4-file cycle: `common/imgur_storage.py -> common/tasks.py -> incident/models.py -> common/models.py -> common/imgur_storage.py`

## Hyperedges (group relationships)
- **Canary Progressive Delivery Flow** — _k8s_charts_templates_app_canary_flagger_canary, _k8s_charts_templates_app_deployment_app_deployment, _k8s_charts_templates_app_hpa_hpa, _k8s_charts_templates_app_canary_analysis [EXTRACTED 1.00]
- **CI/CD Image Pipeline** — _github_workflows_push_image_ghcr_ghcr_build_push, _k8s_charts_values_helm_values, _github_workflows_cleanup_image_retention_policy [INFERRED 0.85]
- **Nine Django apps plus rosak project forming MLPTF community platform** — docs_apps_operation, docs_apps_common, docs_apps_spotting, docs_apps_incident, docs_apps_chartography, docs_apps_telegram_provider, docs_apps_generic, docs_apps_reporting, docs_apps_mlptf, docs_apps_rosak_project [EXTRACTED 1.00]
- **Docker Compose stack nginx granian PostGIS Redis Celery worker and beat** — docker_compose_nginx_web, docker_compose_granian_app, docker_compose_postgis_db, docker_compose_timescaledb, docker_compose_redis, docker_compose_celeryworker, docker_compose_celerybeat [EXTRACTED 1.00]
- **Strawberry GraphQL 0.243 to 0.323 Maybe pattern migration across six waves** — docs_strawberry_migration_maybe, docs_strawberry_migration_filter_decorator, docs_strawberry_migration_connection, agents_strawberry_maybe, django_5_2_upgrade_strfilterlookup [EXTRACTED 1.00]

## Communities (244 total, 113 thin omitted)

### Community 0 - "Incident Domain Core"
Cohesion: 0.10
Nodes (46): sync_to_async, User, CalendarIncidentChronology, get_incident(), is_author(), may_edit(), Author/admin access rules and incident lookup shared by the services., approve_chronology() (+38 more)

### Community 1 - "Jejak Bus Data Schema"
Cohesion: 0.06
Nodes (26): Bus, LocationFilter, filter, BusOrder, LocationOrder, order, Bus, BusType (+18 more)

### Community 2 - "Bus Range Abstract Models"
Cohesion: 0.10
Nodes (39): ForeignKeyCompositeIdentifierDetailAbstractModel, IdentifierDetailAbstractModel, Meta, RangeAbstractModel, Accessibility, AccessibilityBusRange, Bus, BusRouteRange (+31 more)

### Community 3 - "URL Extraction Service"
Cohesion: 0.07
Nodes (35): AsyncBaseTransport, CONFIGURED, HttpResponse, extract_data_from_url(), ExtractionError, Exception, Proxy to the extractIncidentData Firebase callable function. The function…, The extraction call failed at the transport, protocol, or function level. (+27 more)

### Community 4 - "Operation DataLoaders & Imports"
Cohesion: 0.09
Nodes (30): DataFrame, defaultdict, LazyFrame, Model, batch_load_incident_from_vehicle(), batch_load_spottings_from_vehicle(), batch_load_vehicle_from_line(), batch_load_vehicle_from_vehicle_type() (+22 more)

### Community 5 - "Chartography Snapshots"
Cohesion: 0.10
Nodes (24): LineVehicleStatusCountHistoryAdmin, LineVehicleStatusCountHistoryTabularInline, SnapshotAdmin, SourceAdmin, SourceCustomLineAdmin, DataSources, LineVehicleStatusCountHistory, Meta (+16 more)

### Community 6 - "Async ORM Tests"
Cohesion: 0.07
Nodes (12): AsyncOrmRegressionTests, EventCheckConstraintTests, LocationEventTests, TestCase, Test that filter decorators are correctly applied., Verify EventFilter has correct strawberry_django decorator., Daily-report fan-out through the governed egress path., Regression tests for the Django async ORM API surface (4.2 -> 5.x). (+4 more)

### Community 7 - "Operation GraphQL Filters"
Cohesion: 0.08
Nodes (28): AssetFilter, LineFilter, filter, filter_field, ID, Q, StationFilter, StationLineFilter (+20 more)

### Community 8 - "Timescale DB Router"
Cohesion: 0.06
Nodes (19): Attempts to read timescale models go to timescale_db read replicas., Attempts to write timescale models go to timescale_db., A router to control all database operations on models in the auth and…, Allow relations if databases are same., Make sure the timescale apps only appear in the 'timescale' database., TimescaleRouter, SimpleTestCase, jejak app migration should be allowed on timescale DB. (+11 more)

### Community 9 - "Incident Admin & GIS Forms"
Cohesion: 0.07
Nodes (29): display, GeometricForm, Meta, A form class that changes map djang-admin to latitute and longitude fields. For…, CalendarIncidentAdmin, CalendarIncidentAdminForm, CalendarIncidentCategoryAdmin, CalendarIncidentChronologyAdmin (+21 more)

### Community 10 - "Imgur Media Storage"
Cohesion: 0.06
Nodes (16): BaseCommand, ImgurClient, ImgurFile, ImgurStorage, use a file descriptor to perform a make_request, Returns a filename that's free on the target storage system, and available for…, A storage class providing access to resources in an Imgur album., Command (+8 more)

### Community 11 - "Chronology Mutations"
Cohesion: 0.18
Nodes (20): GenericMutationReturn, CalendarIncidentInput, ChronologyMutations, ID, mutation, type, IncidentCrudMutations, ID (+12 more)

### Community 12 - "Social Link Console Queries"
Cohesion: 0.12
Nodes (24): CalendarIncidentCategory, SocialMediaLink, get_calendar_incident_categories(), get_public_social_media_links(), get_social_media_links(), ID, Maybe, Console social-media-link queue, newest submissions first. (+16 more)

### Community 13 - "Line & Vehicle Resolvers"
Cohesion: 0.14
Nodes (10): Line, date, field, lazy, Maybe, type, Vehicle, VehicleType (+2 more)

### Community 14 - "Governed Egress Tests"
Cohesion: 0.12
Nodes (20): Message, RuntimeError, task, report_spotting_today(), patch, Pure-async retry helper, each coroutine driven via asyncio.run(). Deliberately…, Governed egress end-to-end with the DB layer mocked out. TestCase (not…, RetryOnErrorTests (+12 more)

### Community 15 - "Common Task Tests"
Cohesion: 0.07
Nodes (9): CleanupExpiredVerificationCodesTaskTests, CleanupTemporaryMediaTaskTests, CommonModelTests, TestCase, Test migration sets correct defaults for spotting_data_public, After migration, new users should have spotting_data_public=False, SpottingDataPublicMigrationTests, TemporaryMediaSignalTests (+1 more)

### Community 16 - "Tri-State Input Tests"
Cohesion: 0.09
Nodes (15): TestUserInput, input, WebLocationInput, GenericPrimitivesTests, TestCase, TestWebLocationInput, partial, assert_maybe_field_behavior() (+7 more)

### Community 17 - "Incident Scalars"
Cohesion: 0.14
Nodes (19): CalendarIncidentOrder, order, CalendarIncidentCategoryScalar, CalendarIncidentChronologyScalar, CalendarIncidentGroupByDateSeverityScalar, CalendarIncidentScalar, _content_type_id(), ExtractedIncidentDataScalar (+11 more)

### Community 18 - "Spotting Enums & Migrations"
Cohesion: 0.11
Nodes (17): Meta, WebLocationModel, SpottingDataSource, SpottingEventType, SpottingVehicleStatus, SpottingWheelStatus, Migration, Migration (+9 more)

### Community 19 - "Operation Models & Migrations"
Cohesion: 0.13
Nodes (18): AssetStatus, AssetType, LineStatus, WheelStatus, Migration, Migration, Migration, Asset (+10 more)

### Community 20 - "Incident Soft-Delete Models"
Cohesion: 0.12
Nodes (21): CalendarIncidentChronologyIndicator, CalendarIncidentSeverity, CalendarIncidentStatus, IncidentSeverity, CalendarIncidentMedia, IncidentAbstractModel, Meta, TimeStampedModel (+13 more)

### Community 21 - "Dev Tooling Config"
Cohesion: 0.08
Nodes (28): command, enabled, type, GITHUB_PERSONAL_ACCESS_TOKEN, command, enabled, environment, type (+20 more)

### Community 22 - "Backend Progress Logs"
Cohesion: 0.08
Nodes (28): 2026-08-06: Update dependencies (Other, fab9b3b), 2026-08-14: Add docs (ed3ae0a), 2026-08-17: Fix migration imports and MCP servers (6 commits), 2026-08-18: Django 5.2 upgrade, Jejak capabilities, Telegram fix (10 commits), 2026-08-19: Strawberry GraphQL Maybe[T] 4-phase migration and docs (11 commits), 2026-08-21: Incident Vote, SocialMediaLink, CalendarIncidentStatus core models (4 commits), 2026-08-22: Incident feature wave 25 commits - CRUD, voting, Celery purge, submit workflow, 2026-08-24: Fixes (NSFW, public_user, advanced_filters) and incident filter/docs (12 commits) (+20 more)

### Community 23 - "Telegram Handlers"
Cohesion: 0.16
Nodes (22): Protocol, ASGILifespanSignalHandler, HTTPXAppConfig, AppConfig, TelegramProviderConfig, dad_joke(), delete(), delete_link() (+14 more)

### Community 24 - "Reporting Admin"
Cohesion: 0.11
Nodes (20): ReportAdmin, ReportMediaStackedInline, ReportResolutionStackedInline, ReportStackedInline, ResolutionAdmin, ResolutionStackedInline, VoteAdmin, VoteStackedInline (+12 more)

### Community 25 - "Common Admin"
Cohesion: 0.09
Nodes (17): ClearanceAdmin, FeatureFlagAdmin, MediaAdmin, MediaStackedInline, MediaTabularInline, TemporaryMediaAdmin, UserAdmin, UserClearanceStackedInline (+9 more)

### Community 26 - "Incident Tasks & Workflows"
Cohesion: 0.19
Nodes (24): get_pending_calendar_incidents(), Console approval queue: PENDING_APPROVAL incidents, oldest first., purge_rejected_incidents(), purge_soft_deleted_incidents(), task, Hard-delete incidents soft-deleted more than 90 days ago., Hard-delete visible REJECTED incidents unchanged for over 30 days. Soft-deleted…, _backdate() (+16 more)

### Community 27 - "Trend Date Utilities"
Cohesion: 0.12
Nodes (18): TestDateUtilities, get_combinations(), get_date_key(), get_default_start_time(), get_group_strs(), get_result_comparison_tuple(), get_trends(), date (+10 more)

### Community 28 - "Common GraphQL Tests"
Cohesion: 0.12
Nodes (6): CommonGraphQLTests, TestDjangoListConnection, TestUpdateUserMutation, execute_graphql_async(), Maybe[T] migration tests for the add_event mutation. Maybe semantics: omitted…, TestAddEventMutation

### Community 29 - "Vote DataLoaders"
Cohesion: 0.16
Nodes (21): Meta, Universal voting model using ContentType framework for upvote/downvote on any…, Vote, batch_load_user_vote_value(), batch_load_vote_breakdown(), batch_load_vote_scores(), Batch load net vote scores (sum of vote values). Keys: list of…, Batch load vote breakdown (upvote/downvote counts). Keys: list of… (+13 more)

### Community 30 - "Incident Interaction Mutations"
Cohesion: 0.17
Nodes (15): CalendarIncidentChronologyInput, ExtractDataInput, input, SocialMediaLinkInput, Chronology CRUD and reorder mutations., ExtractionMutations, ID, mutation (+7 more)

### Community 31 - "Incident GraphQL Filters"
Cohesion: 0.20
Nodes (12): CalendarIncidentDateFilter, CalendarIncidentFilter, DateRangeInput, IncidentAbstractFilter, IntExactInput, filter, input, StationIncidentFilter (+4 more)

### Community 32 - "Mutation Resolver Tests"
Cohesion: 0.23
Nodes (20): _Context, _incident_input(), _make_user(), no_admin_claim(), django_db, fixture, GraphQL mutation-layer tests: the thin resolver wrappers around the services.…, _service_write() (+12 more)

### Community 33 - "Common Schema & Permissions"
Cohesion: 0.15
Nodes (15): BasePermission, CommonMutations, IsLoggedIn, IsRecaptchaChallengePassed, EventOrder, order, get_events_count(), LocationEvent (+7 more)

### Community 34 - "Egress & Subscription Concepts"
Cohesion: 0.10
Nodes (21): BoundedRetry, DeadLetterQueue, spotting.tasks.report_spotting_today, telegram_provider.utils.send_message, settings.TELEGRAM_ADMIN_CHAT_ID, telegram_provider.models.TelegramLogs, DigestFormat, spotting.EventRead (+13 more)

### Community 35 - "Operation Admin"
Cohesion: 0.11
Nodes (20): AssetAdmin, AssetMediaStackedInline, AssetMediaTabluarInline, AssetStackedInline, AssetTabularInline, LineAdmin, LineStackedInline, AdminAdvancedFiltersMixin (+12 more)

### Community 36 - "Link Handler Tests"
Cohesion: 0.39
Nodes (3): submit_link(), LinkHandlerTests, Coverage for /link (submit_link) and /deletelink (delete_link) handlers. Plain…

### Community 37 - "TemporaryMedia Lifecycle"
Cohesion: 0.19
Nodes (16): ClearanceType, TemporaryMediaStatus, TemporaryMedia, UserVerificationCode, input, UserInput, convert_temporary_media_to_media(), check_temporary_media_nsfw() (+8 more)

### Community 38 - "Media Field Migrations"
Cohesion: 0.13
Nodes (10): ImgurImageFieldFile, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+2 more)

### Community 39 - "Incident GraphQL Integration Tests"
Cohesion: 0.15
Nodes (4): execute_graphql(), IncidentSchemaExecutionTests, SocialMediaLinkTests, TestCalendarIncidentResolvers

### Community 40 - "Credit & Clearance Models"
Cohesion: 0.23
Nodes (9): CreditType, FeatureFlagType, TemporaryMediaType, UserJejakTransactionCategory, UserJejakTransaction, FirebaseUser, get_charge_credits_objs(), HttpRequest (+1 more)

### Community 41 - "Severity Count Tests"
Cohesion: 0.25
Nodes (16): get_calendar_incidents_by_severity_count(), GroupByEnum, date, enum, _make_incident(), date, datetime, django_db (+8 more)

### Community 42 - "Jejak Degradation Tests"
Cohesion: 0.19
Nodes (7): execute_graphql(), get_graphql_context(), GracefulDegradationGraphQLTests, GracefulDegradationSettingsTests, override_settings, SimpleTestCase, TestCase

### Community 43 - "User Scalar Resolvers"
Cohesion: 0.20
Nodes (9): date, field, lazy, Maybe, UserScalar, FavouriteVehicleData, type, UserSpottingTrend (+1 more)

### Community 44 - "Operation Model Tests"
Cohesion: 0.11
Nodes (7): OperationModelTests, TestCase, Test that filter decorators are correctly applied., Verify LineFilter has correct strawberry_django decorator., Verify StationFilter has correct strawberry_django decorator., SimpleHistoryTests, TestFilterDecorators

### Community 45 - "Spotting Trend Tests"
Cohesion: 0.15
Nodes (5): filter_field, Q, Incidents with no end date yet — independent of any `date` window, so a client…, TestTrendsResolvers, SpottingGraphQLTests

### Community 46 - "Event Scalars & Inputs"
Cohesion: 0.16
Nodes (8): DeleteEventInput, MarkEventAsReadInput, input, EventScalar, field, sync_to_async, mutation, sync_to_async

### Community 47 - "GraphQL View Tests"
Cohesion: 0.15
Nodes (10): AsyncGraphQLView, ExecutionResult, GraphQLHTTPResponse, CustomGraphQLView, Any, HttpRequest, TestCase, Verify multipart uploads setting per Strawberry 0.243.0 defaults (disabled). (+2 more)

### Community 48 - "Incident Workflow Tests"
Cohesion: 0.43
Nodes (14): _make_user(), django_db, test_admin_creates_live(), test_approve_merges_draft_to_parent(), test_approve_requires_pending_for_non_revision(), test_delete_rules(), test_optimistic_concurrency_control(), test_reject_records_reason_and_status() (+6 more)

### Community 49 - "CI/CD & K8s Deploy"
Cohesion: 0.15
Nodes (14): Container Retention Policy, Scheduled GHCR Cleanup Workflow, Docker Buildx Multi-Arch Build, GHCR Build and Push Workflow, Git Metadata Tagging, Helm Chart Backend, Canary Analysis Metrics, Flagger Canary Deployment (+6 more)

### Community 50 - "Chartography Mutations"
Cohesion: 0.24
Nodes (9): input, TriggerInput, ChartographyMutations, ChartographyScalars, mutation, type, type, ReportingMutations (+1 more)

### Community 51 - "Media Loaders"
Cohesion: 0.15
Nodes (8): Migration, Migration, batch_load_media_from_id(), batch_load_spottings_from_user(), Migration, Event, Meta, UUID

### Community 52 - "Privacy Enforcement Tests"
Cohesion: 0.14
Nodes (8): Tests for User.spotting_data_public privacy logic, New users should have private spotting data by default, publicUser(id:) query should return user when Firebase uid exists, publicUser(id:) should return null for a non-existent Firebase uid, Owner's spottings should be null for non-owners when private, Owner's spottings should be visible when spotting_data_public=True, Owner should always see their own spottings regardless of flag, UserPrivacyTests

### Community 53 - "Incident Write Services"
Cohesion: 0.27
Nodes (12): CalendarIncident, _apply_field_update(), _apply_m2m(), ChronologyWrite, create_incident(), _create_revision(), IncidentWrite, _merge_revision_into_parent() (+4 more)

### Community 54 - "Incident Unit Gap Tests"
Cohesion: 0.33
Nodes (13): batch_load_medias_from_calendar_incident(), _make_user(), django_db, override_settings, Edge-case unit tests filling the Wave 5 coverage gaps (services, models,…, test_admin_can_submit_any_draft(), test_medias_loader_groups_by_incident_and_defaults_empty(), test_model_str_and_admin_widget_render() (+5 more)

### Community 55 - "Incident Model Tests"
Cohesion: 0.14
Nodes (6): IncidentModelTests, TestCase, Test that filter decorators are correctly applied., Verify CalendarIncidentFilter has correct strawberry_django decorator., Verify VehicleIncidentFilter has correct strawberry_django decorator., TestFilterDecorators

### Community 56 - "Telegram Provider Module"
Cohesion: 0.30
Nodes (7): IntegerChoices, MessageDirection, TimeStampedModel, TelegramLogs, TelegramSocialMediaLinkLog, cleanup_telegram_logs(), task

### Community 57 - "Schema Assembly Tests"
Cohesion: 0.21
Nodes (5): execute_graphql(), get_graphql_context(), SimpleTestCase, RosakSchemaExecutionTests, RosakSchemaTests

### Community 58 - "Telegram Admin Notify Tests"
Cohesion: 0.19
Nodes (6): error_handler(), CleanupTelegramLogsTaskTests, ErrorHandlerTests, TestCase, Admin notification branch of the PTB error handler. Touches no DB —…, TelegramProviderModelTests

### Community 59 - "Media Mixin"
Cohesion: 0.17
Nodes (5): ImgurField, MediaMixin, Media, UUIDModel, ImageField

### Community 60 - "Common Scalars"
Cohesion: 0.21
Nodes (8): MediaOrder, order, MediaScalar, MediasGroupByPeriodScalar, MediaType, type, UserVerificationCodeScalar, mutation

### Community 61 - "Incident Integration Tests"
Cohesion: 0.42
Nodes (12): _backdate(), _make_user(), django_db, End-to-end workflow tests spanning services, votes, and purge tasks., test_edit_live_merge_preserves_votes(), test_full_lifecycle_draft_to_live_to_soft_deleted(), test_rejected_purge_after_30_days(), test_soft_delete_purge_after_90_days_cascades_votes() (+4 more)

### Community 62 - "Vote Mutation Tests"
Cohesion: 0.39
Nodes (11): _incident_content_type(), _make_incident(), _make_user(), ContentType, django_db, test_downvote_creates_vote(), test_remove_vote(), test_upvote_changes_downvote() (+3 more)

### Community 63 - "Clearance Migrations"
Cohesion: 0.22
Nodes (8): add_clearance(), Migration, add_data(), Migration, Clearance, FeatureFlag, TimeStampedModel, UserClearance

### Community 64 - "Jejak Admin"
Cohesion: 0.22
Nodes (6): BusAdmin, BusTypeAdmin, LocationAdmin, LocationPaginator, AdminAdvancedFiltersMixin, Paginator

### Community 65 - "Schema Build Tests"
Cohesion: 0.33
Nodes (10): Mutation, type, Query, _build_schema(), _field_names(), django_db, Schema-assembly tests: the full GraphQL contract builds and exposes the waves'…, test_incident_input_and_enum_types_are_in_schema() (+2 more)

### Community 66 - "Telegram Link Parser"
Cohesion: 0.20
Nodes (3): ArgumentParser, Formatter, link_parser()

### Community 67 - "Chronology Mutation Tests"
Cohesion: 0.56
Nodes (9): _chronology_write(), _make_incident(), _make_user(), django_db, test_chronology_cannot_be_approved_if_parent_not_live(), test_chronology_inherits_parent_status_on_creation(), test_chronology_reorder(), test_chronology_update_and_soft_delete() (+1 more)

### Community 68 - "Shared Schema Types"
Cohesion: 0.33
Nodes (5): type, Source, LineVehicleSpottingTrend, type, VehicleSpottingTrend

### Community 69 - "Per-Chat Rate Limiter"
Cohesion: 0.28
Nodes (4): PerChatRateLimiterTests, Sliding-window limiter: default budget, per-chat isolation, rollover., PerChatRateLimiter, Thread-safe in-process sliding-window rate limiter, per chat. Allows at most…

### Community 70 - "Social Link Model Tests"
Cohesion: 0.22
Nodes (4): TestCase, SocialMediaLink can link to CalendarIncident via GenericForeignKey, SocialMediaLink can exist without being tagged to any object (just dumping), SocialMediaLinkTests

### Community 71 - "Upload API View"
Cohesion: 0.25
Nodes (7): atomic, GenericUpload, APIView, async_to_sync, HttpRequest, Request, Possible values: - upload_type - image - related_id

### Community 72 - "Public User Queries"
Cohesion: 0.32
Nodes (5): CommonScalars, field, ID, type, Fetch any user's public profile by ID. Public stats are always visible;…

### Community 73 - "Admin Prettify Mixins"
Cohesion: 0.32
Nodes (4): JsonPrettifyAdminMixin, Return html formatted json body dict with style Taken from…, AdminAdvancedFiltersMixin, TelegramLogAdmin

### Community 75 - "Chronology Status Tests"
Cohesion: 0.25
Nodes (4): CalendarIncidentChronologyTests, TestCase, Chronology CAN be LIVE when parent incident is LIVE., Chronology status is independent - can be different from parent.

### Community 76 - "Social Link Mutation Tests"
Cohesion: 0.54
Nodes (7): _make_incident(), _make_user(), django_db, test_mark_social_media_link_completed_records_admin_user(), test_submit_social_media_link_title_null_and_omitted_coerce_to_empty(), test_submit_social_media_link_with_and_without_incident(), test_submit_social_media_link_with_line_vehicle_station_tags()

### Community 77 - "Common App Constraints"
Cohesion: 0.29
Nodes (7): tach.yml cross-app import boundaries, common app identity media analytics substrate, TemporaryMedia → Discord CDN → Media staged state machine, PTB Application ASGI lifespan webhook registration, ImgurStorage on hot path for every Media creation, infinite_retry_on_error unbounded retry pinning worker, NSFW moderation bypass all uploads convert unchecked

### Community 78 - "Spotting & Telegram Concepts"
Cohesion: 0.29
Nodes (7): spotting app sighting ledger, telegram_provider app Telegram bridge, Vehicle rolling-stock with VehicleStatus, Event vehicle sighting ledger aggregate root, spotting_parser argparse grammar for /spot command, TelegramLogs raw payload audit log with MessageDirection, get_daily_updates overwrites spotting_date with date.today

### Community 79 - "Station Accessibility Feature"
Cohesion: 0.29
Nodes (7): batch_load_assets_from_station DataLoader, AssetStatusEnum, operation.Asset, reporting.Report, reporting.Vote, StationAccessibility, incident.StationIncident

### Community 80 - "Project Entrypoints"
Cohesion: 0.29
Nodes (3): debug_task(), task, rosak URL Configuration The `urlpatterns` list routes URLs to views. For more…

### Community 81 - "Settings & Sentry"
Cohesion: 0.38
Nodes (4): filter_transactions(), Django settings for rosak project. Generated by 'django-admin startproject'…, Convert a string representation of truth to true (1) or false (0). True values…, strtobool()

### Community 82 - "Schema Snapshot Tests"
Cohesion: 0.29
Nodes (4): TestCase, Ensure current schema matches the committed SDL snapshot baseline., Ensure no breaking changes exist compared to the baseline SDL., TestSchemaSnapshot

### Community 83 - "Incident Workflow Concepts"
Cohesion: 0.33
Nodes (6): incident app disruption record, operation app reference-data hub, CalendarIncident network-level disruption span, Line canonical transit line reference, Dual Line ↔ CalendarIncident join tables permanently empty GraphQL field, Calendar incident DRAFT→PENDING_APPROVAL→LIVE/REJECTED workflow

### Community 84 - "Telegram Inbound View"
Cohesion: 0.33
Nodes (5): APIView, async_to_sync, HttpRequest, Request, TelegramInbound

### Community 85 - "GIS Location Concepts"
Cohesion: 0.40
Nodes (5): PostGIS db service postgis/postgis:17-3.5-alpine, generic app table-less shared kernel, GeometricForm lat/long admin widget, WebLocationModel abstract GIS model, LocationEvent GPS payload extending WebLocationModel

### Community 86 - "Impact Factor Feature"
Cohesion: 0.40
Nodes (5): CalendarIncident.impact_factor, compute_line_reliability_scores, LineReliabilityScore, ReliabilityTrend, suggested_impact_factor

### Community 87 - "Geo Search Fields"
Cohesion: 0.70
Nodes (4): GeometricSearchField, Point2D, Point2D_SearchField, TypedDict

### Community 89 - "CI Test Gates"
Cohesion: 0.50
Nodes (4): CI Test Workflow, Django Verification Gate, Ruff Lint and Format Gate, Ruff Pre-commit Hook

### Community 91 - "Reporting Concepts"
Cohesion: 0.50
Nodes (4): reporting app asset defects dormant, Asset lift escalator station asset, Report crowd-sourced asset defect report, Vote corroboration with ballot stuffing gap

### Community 93 - "Semaphore Deploy"
Cohesion: 0.67
Nodes (3): Semaphore Deploy Pipeline, Sentry Release Process, Semaphore Legacy Docker Pipeline

### Community 94 - "Strawberry Maybe Pattern"
Cohesion: 0.67
Nodes (3): strawberry.Maybe[T] tri-state optional inputs, StrFilterLookup replacing FilterLookup[str] for DuplicatedTypeName fix, strawberry.Maybe[T] tri-state UNSET/Some(value)/Some(None)

### Community 97 - "Celery Services"
Cohesion: 0.67
Nodes (3): Celery beat service, Celery worker service, Redis cache and Celery broker

### Community 98 - "Chartography Concepts"
Cohesion: 0.67
Nodes (3): chartography app time-series ledger, Snapshot daily point-in-time per line status counts, impact_factor reliability deduction score

### Community 99 - "Badge Concepts"
Cohesion: 0.67
Nodes (3): mlptf app badges, Badge community award model, UserBadge through-model award relation

## Knowledge Gaps
- **254 isolated node(s):** `Migration`, `Migration`, `Migration`, `Migration`, `SourceAdmin` (+249 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 803 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **113 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `Incident Domain Core` to `Chartography Snapshots`, `Social Link Console Queries`, `Spotting Enums & Migrations`, `Operation Models & Migrations`, `Incident Soft-Delete Models`, `Telegram Handlers`, `Reporting Admin`, `Common Admin`, `Incident Tasks & Workflows`, `Vote DataLoaders`, `Mutation Resolver Tests`, `Common Schema & Permissions`, `TemporaryMedia Lifecycle`, `Credit & Clearance Models`, `Incident Workflow Tests`, `Incident Write Services`, `Incident Unit Gap Tests`, `Incident Integration Tests`, `Vote Mutation Tests`, `Clearance Migrations`, `Chronology Mutation Tests`, `Social Link Mutation Tests`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `execute_graphql_async()` connect `Common GraphQL Tests` to `Jejak Bus Data Schema`, `TemporaryMedia Lifecycle`, `Spotting Trend Tests`, `Spotting Enums & Migrations`, `Privacy Enforcement Tests`, `Schema Assembly Tests`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `_Info` connect `Line & Vehicle Resolvers` to `Mutation Resolver Tests`, `Jejak Bus Data Schema`, `URL Extraction Service`, `Operation GraphQL Filters`, `Public User Queries`, `Chronology Mutations`, `User Scalar Resolvers`, `Event Scalars & Inputs`, `Incident Scalars`, `Chartography Mutations`, `Common Scalars`, `Incident Interaction Mutations`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **What connects `Migration`, `Migration`, `Migration` to the rest of the system?**
  _254 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Incident Domain Core` be split into smaller, more focused modules?**
  _Cohesion score 0.09730301427815971 - nodes in this community are weakly interconnected._
- **Should `Jejak Bus Data Schema` be split into smaller, more focused modules?**
  _Cohesion score 0.05786090005844535 - nodes in this community are weakly interconnected._
- **Should `Bus Range Abstract Models` be split into smaller, more focused modules?**
  _Cohesion score 0.09948979591836735 - nodes in this community are weakly interconnected._

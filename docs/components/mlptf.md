# Component: mlptf

## 📌 Purpose & Scope

- **Core Responsibility:** The organisational-recognition domain for MLPTF (Malaysia Land Public Transport Forum, behind the TranSPOT / `community.mlptf.org.my` platform). It models **badges** and their many-to-many award relation to `common.User`, and nothing else.
- **Scope reality:** The thinnest app in the project. It has two models, one admin registration with one inline, one migration and one test class (a single award test in `mlptf/tests.py`). It has no `views.py`, `urls.py`, `schema/`, `tasks.py`, signals or serializers. Treat it as a **stub domain**: data that exists and is wired into `common.User`, with no runtime behaviour of its own.
- **What it is not:** It does not model org membership, chapters, committees, subscriptions or roles. Identity lives in `common.User`; authorisation lives in `common.Clearance` / `common.UserClearance`.
- **Naming caveat:** The string `mlptf` also appears for unrelated reasons. `chartography.enums.DataSources.MLPTF` is a fleet-data provenance value, and `chartography.tasks.aggregate_line_vehicle_status_mlptf_task` is a beat job at `crontab(hour=5)`, local time (`Asia/Kuala_Lumpur`). Neither imports this app.
- **Domain/Layer:** Django persistence and Django Admin. No API layer, no business-logic layer.

## 🔌 Interface & Data Flow

### Models (`mlptf/models.py`)

Both models extend `model_utils.models.TimeStampedModel`, so both carry `created` / `modified`. Neither has a `Meta`, `__str__`, `save()` or `clean()`. That means no ordering, `verbose_name`, constraints or `db_table`, and both render as `Badge object (N)` in admin.

| Model | Field | Type | Notes |
|---|---|---|---|
| `Badge` | `name` | `CharField(max_length=64)` | Required, no uniqueness |
| | `description` | `TextField(default="", blank=True)` | Optional prose |
| | `released` | `DateField()` | Required, no default. The "minted on" date. Nothing filters on it. |
| | `sprite_url` | `URLField()` | Required external image URL. Not a `FileField`, so it bypasses the media pipeline (`common.views.GenericUpload`, `django_cleanup`). |
| | `users` | M2M → `common.User` through `UserBadge` | Reverse side of the award relation |
| `UserBadge` | `user` | `FK → common.User (CASCADE)` | Explicit through-model |
| | `badge` | `FK → mlptf.Badge (CASCADE)` | |

- **Inputs:** None programmatic. The only write path is the Django Admin, both `/admin/` and the inline on the `common.User` admin.
- **Outputs:** None. `rosak/schema.py` does not compose any `mlptf` root, and `rosak/urls.py` mounts no route. `common/schema/` has no `badge` field on `User`, so badges are not reachable transitively either. Nothing outside admin reads or writes a badge.
- **Dependencies:** `common.User` (FK and M2M target), `django-model-utils`, Django admin. No third-party integration, Celery, Redis or HTTP.

### Cross-app references (inbound)

- `common/models.py` (`User.badges`): `ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")`.
- `common/migrations/0002_user_badges.py` depends on `mlptf.0001_initial`. `mlptf` therefore sits on `common`'s migration critical path and cannot be removed without schema surgery.
- `common/admin.py` imports `UserBadgeStackedInline` and mounts it on `UserAdmin.inlines` next to `UserClearanceStackedInline`. This is the one place `mlptf` code runs inside another app.
- `rosak/settings.py` lists it in `INSTALLED_APPS`.

The app-level graph has a two-node cycle (`mlptf → common` for models, `common → mlptf` for the admin inline). It resolves only because both edges are lazy: string model references and an admin-time import.

## ⚙️ Internal State & Logic

- **No logic.** There are no `save()`, `clean()` or signal hooks.
- **Integrity gap:** No `UniqueConstraint` on `UserBadge(user, badge)`. The same badge can be awarded to the same user any number of times, and the inline offers no guard.
- **Awarding is entirely manual.** Nothing derives eligibility from `spotting`, `incident` or `reporting` activity, even though those apps hold the signals.
- **Schema:** One migration, `0001_initial`, creates both models and the `users` M2M. The shape has not changed since.

## 🧩 Extension Points & Hooks

Few, and all are conventions rather than designed seams.

- **`UserBadgeStackedInline`** (`mlptf/admin.py`): the one exercised extension point. `common.admin.UserAdmin` reuses it, and any other `User`-adjacent admin can mount it the same way.
- **`BadgeAdmin`**: accepts `list_filter`, `readonly_fields` or actions (for example a bulk "award to selected users") without touching models.
- **`UserBadge` as an explicit through-model**: the standard seam for award metadata (`awarded_by`, `reason`, `revoked`). `UserBadge.created` already gives the award timestamp.
- **Absent but cheap:** A `mlptf/schema/` package appended to `rosak/schema.py` follows the per-app pattern exactly. A `mlptf/tasks.py` is picked up by `app.autodiscover_tasks()`, and a `beat_schedule` entry goes in `rosak/celery.py`. Neither exists, so any badge feature starts with net-new plumbing.
- No signals, custom managers, middleware or permissions beyond Django's model permissions.

## 💡 Potential Feature Opportunities

Everything below is ordinary product and engineering work. **Item 1 is the gate.** Until badges reach GraphQL, `Badge` and `UserBadge` stay a write-only admin table and every other item ships invisibly.

1. **Read-only badge exposure on the GraphQL user graph.** Add `mlptf/schema/` with a `BadgeScalar` (`name`, `description`, `released`, `sprite_url`) and a `MlptfScalars` mixin appended to `rosak/schema.py`'s `Query` bases. Add a `badges` resolver to `common/schema/scalars.py::UserScalar`, batched through a new loader in `common/schema/loaders.py` registered in `CommonContextLoaders`. Mirror the existing `spottings_from_user_loader` to avoid N+1. "Earned on" is `UserBadge.created`.
   **Readiness:** `Not ready`. Net-new plumbing, but it follows an established pattern.

2. **Rule-based nightly awarding (Celery).** The inputs already sit in adjacent tables: `spotting.Event` by `reporter_id`, `Event.vehicle` → `operation.Vehicle.lines`, `Event.type`, the `operation.VehicleLine` roster and `common.User.created`. All of it is plain `COUNT` / `GROUP BY`. The task template is `spotting/tasks.py::report_spotting_today` (`@celery_app.task(bind=True)`). Announcements go through `telegram_provider.utils.send_message` to `operation.Line.telegram_channel_id`, as `report_spotting_today` does. Full spec: `docs/features/05-badges-digests-contribution-loop.md`.
   **Readiness:** `Partially ready`. Three blockers. (a) Add `UniqueConstraint(user, badge)` with a `mlptf/migrations/0002_*.py`, then use `get_or_create` or `bulk_create(ignore_conflicts=True)`. Without it a nightly run re-awards every night. (b) Decide the rule → badge mapping: a unique `Badge.code` or `slug`, or a code-side registry keyed on badge id. (c) Decide whether `Event.is_anonymous=True` rows count. The new beat entry goes in `rosak/celery.py`.

3. **Badge rarity and holder listings.** `Badge.objects.annotate(holder_count=Count("users"))` gives "held by N members" labels and a holder list. The repo already aggregates this way in `CommonScalars.medias_group_by_period` (`common/schema/schema.py`). Full spec in `docs/features/05-badges-digests-contribution-loop.md`.
   **Readiness:** `Not ready`. It needs item 1 first. Counts double-count until item 2's uniqueness constraint lands.

4. **Scheduled reveals using `Badge.released`.** Treat `released` as a publish date: `filter(released__lte=date.today())` in the public resolver. Add `list_filter = ["released"]` and `date_hierarchy = "released"` to `BadgeAdmin` so staff can see what is scheduled. Decide whether an unreleased badge may be awarded, since it can be today.
   **Readiness:** `Partially ready`. The field exists and is populated. The resolver (item 1) and the admin edits are missing.

5. **Badge sprites in the project's media pipeline.** `sprite_url` lives on an unmanaged third-party host. Nothing checks that it resolves, `django_cleanup` cannot collect it, and a dead host breaks every profile that shows the badge. Pointing badges at `common.Media` (as `spotting.EventMedia`, `operation.StationMedia` and `operation.AssetMedia` do) gives artwork the same lifecycle and makes sprite dimensions enforceable.
   **Readiness:** `Not ready`. Add `Badge.sprite = FK("common.Media", null=True)` and `mlptf/migrations/0002_*.py`, backfill by downloading each `sprite_url`, then deprecate the URL field in a later migration. The item-1 resolver prefers `sprite` and falls back to `sprite_url`.

## 💡 Potential AI Feature Opportunities

1. **Inferred badge awarding.** `UserBadge` is an explicit through-model, so a heuristic or model-driven eligibility engine can write awards with no schema change. Add `awarded_by` and `reason` columns for audit. Inputs already exist in `spotting`, `incident` and `chartography` snapshots. A natural first cut is a nightly task that mirrors `chartography.tasks.aggregate_line_vehicle_status_mlptf_task`.
2. **Generated badge copy and artwork.** `description` and `sprite_url` are both hand-filled. An assisted flow could draft descriptions from a badge name and its award criteria, and route generated sprites through `common.views.GenericUpload`.
3. **Personalised contribution nudges.** Once badges are on the GraphQL `User` type, "two more sightings on this line completes X" is a natural recommendation, delivered through the `telegram_provider` bot.

**Before any of the above:** add `__str__` to both models, a `UniqueConstraint` on `UserBadge(user, badge)`, `Meta.ordering` on `Badge`, and at minimum read-only GraphQL exposure.

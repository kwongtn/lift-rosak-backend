# Component: mlptf

## 📌 Purpose & Scope

- **Core Responsibility:** Owns the *organisational-recognition* domain for MLPTF (Malaysia Land
  Public Transport Forum — the community org behind the TranSPOT/`community.mlptf.org.my`
  platform). Concretely, it models **badges** (community awards / achievement sprites) and the
  many-to-many award relation between a badge and a `common.User`.
- **Scope reality check:** This is the thinnest app in the project. It contains exactly two models,
  one admin registration, one inline, one migration, and **nothing else** — no `views.py`, no
  `urls.py`, no `schema/` package, no `tasks.py`, no signals, no serializers, and an empty
  `tests.py`. It should be treated as an **underdeveloped / stub domain**: a data structure that
  exists and is wired into `common.User`, but has no runtime behaviour of its own.
- **What it is *not*:** despite the org-level name, it does **not** model org membership, chapters,
  committees, subscriptions, or roles. Member identity lives in `common.User`; authorisation lives
  in `common.Clearance` / `common.UserClearance`. `mlptf` is *only* badges.
- **Naming caveat:** the string `mlptf` also appears elsewhere in the repo for unrelated reasons —
  `chartography.enums.DataSources.MLPTF` (a fleet-data provenance source) and the
  `aggregate_line_vehicle_status_mlptf_task` Celery beat job. Neither belongs to or imports this
  app. Do not conflate them.
- **Domain/Layer:** Django persistence + Django Admin presentation. No API layer, no business-logic
  layer.

## 🔌 Interface & Data Flow

### Models (`mlptf/models.py`)

Both models extend `model_utils.models.TimeStampedModel`, so both carry auto-managed
`created` / `modified` timestamps.

| Model | Field | Type | Notes |
|---|---|---|---|
| `Badge` | `name` | `CharField(max_length=64)` | Required; no uniqueness constraint |
| | `description` | `TextField(default="", blank=True)` | Optional prose |
| | `released` | `DateField()` | **Required, no default** — badge "minted on" date |
| | `sprite_url` | `URLField()` | **Required** — external image URL; not a `FileField`, so the asset is *not* managed by this project's upload/media pipeline (`common.views.GenericUpload`, `django_cleanup`, Imgur/Discord migration paths) |
| | `users` | `M2M → common.User through mlptf.UserBadge` | Reverse side of the award relation |
| `UserBadge` | `user` | `FK → common.User (CASCADE)` | Explicit through-model |
| | `badge` | `FK → mlptf.Badge (CASCADE)` | |

- **Inputs:** none programmatic. The only write path in the codebase is the Django Admin
  (`/admin/`). Rows can also be created from the `common.User` admin page via the shared inline.
- **Outputs / API surface:** **none.** `rosak/schema.py` composes its Strawberry `Query` /
  `Mutation` from `operation`, `reporting`, `common`, `spotting`, `incident`, and `chartography`
  only — `mlptf` is absent. `rosak/urls.py` mounts no `mlptf` route. A grep of `common/schema/`
  finds no `badge` field on the GraphQL `User` type, so badges are not even reachable
  transitively through the user graph. **Nothing outside the admin can read or write a badge.**
- **Dependencies (outbound):**
  - `common.User` — hard dependency via two FK/M2M targets.
  - `django-model-utils` (`TimeStampedModel`).
  - Django admin.
  - No third-party integration, no Celery, no Redis, no external HTTP.

### Cross-app references (inbound — who depends on `mlptf`)

- `common/models.py` (`User.badges`) — `M2M(to="mlptf.Badge", through="mlptf.UserBadge")`.
- `common/migrations/0002_user_badges.py` — depends on `mlptf.0001_initial`; this is the migration
  that grafts `badges` onto `User`, so **`mlptf` sits on `common`'s migration critical path** and
  cannot be removed without a schema surgery.
- `common/admin.py` — imports `UserBadgeStackedInline` from `mlptf.admin` and mounts it on
  `UserAdmin` alongside `UserClearanceStackedInline`. This is the one place `mlptf` code is
  *executed* by another app.
- `rosak/settings.py` — listed in `INSTALLED_APPS`.

The dependency graph is therefore a tight two-node cycle at the app level
(`mlptf → common` for models, `common → mlptf` for the admin inline), resolved only because both
edges are lazy (string model references + an admin-time import).

## ⚙️ Internal State & Logic

- **There is effectively no logic.** No `save()` override, no `clean()`, no `Meta` block at all —
  meaning no `ordering`, no `verbose_name`, no `unique_together` / `UniqueConstraint`, and no
  `db_table`. No `__str__` on either model, so both render as `Badge object (1)` in admin
  selects and inline headers.
- **Notable integrity gap:** `UserBadge` has no uniqueness constraint on `(user, badge)`, so the
  same badge can be awarded to the same user an unbounded number of times, and the admin inline
  offers no guard against it.
- **Awarding is entirely manual.** Nothing computes badge eligibility from user activity, even
  though the adjacent apps hold exactly the signals you would award on (`spotting` events,
  `incident` reports, `reporting` submissions).
- **Schema evolution:** a single migration, `0001_initial.py` (creates both models and adds the
  `users` M2M). The app has not changed shape since inception — consistent with the Dec-2022 file
  dates on every source file. This is a domain that was scaffolded and then left alone.

## 🧩 Extension Points & Hooks

Honestly: very few, and all of them are conventions rather than designed seams.

- **`UserBadgeStackedInline` (`mlptf/admin.py`)** — the one genuine, already-exercised extension
  point. It is deliberately exported and reused by `common.admin.UserAdmin`, and any other admin
  for a `User`-adjacent model can mount it the same way.
- **`BadgeAdmin`** — registered via `admin.site.register(Badge, BadgeAdmin)`; extendable with
  `list_filter`, `readonly_fields`, or actions (e.g. a bulk "award to selected users" action)
  without touching models.
- **`UserBadge` as an explicit through-model** — the standard Django seam for adding award
  metadata (`awarded_by`, `awarded_at`, `reason`, `revoked`) with no change to `User` or `Badge`.
- **Absent-but-cheap seams:** adding an `mlptf/schema/` package and appending
  `MlptfScalars`/`MlptfMutations` to `rosak/schema.py` would follow the established per-app
  pattern exactly; adding `mlptf/tasks.py` and a `django_celery_beat` entry in `rosak/celery.py`
  likewise. Neither exists today, so any consumer-facing badge feature starts with net-new
  plumbing, not extension.
- **No** signals, no custom managers/querysets, no decorators, no middleware, no permissions
  beyond Django's auto-generated model permissions.

## 💡 Potential Feature Opportunities

Everything below is ordinary product/engineering work — no models, no inference. The honest framing
is that **item 1 is the gate**: `mlptf` has no `schema/` package and is absent from `rosak/schema.py`,
and `common.schema.scalars.UserScalar` has no `badges` field, so badges are unreachable from GraphQL
even transitively. Until that changes, `Badge`/`UserBadge` remain a write-only admin table and every
other item on this list ships invisibly.

1. **Read-only badge exposure on the GraphQL user graph.** Give `mlptf` a `schema/` package
   (`scalars.py` + `schema.py`) with a `BadgeScalar` over `mlptf.Badge` (`name`, `description`,
   `released`, `sprite_url`) and a `badges` field on `common.schema.scalars.UserScalar`, so a profile
   page can render "what has this member earned". The through-model means the award date is already
   available — `UserBadge.created` from `TimeStampedModel` — so an "earned on" timestamp needs no new
   column. For a community rail-transit platform this is the whole point of badges: recognition is
   worthless if only `/admin/` can see it.
   **Readiness:** `Not ready` — net-new plumbing, but it follows an established pattern exactly.
   An implementer creates `mlptf/schema/__init__.py`, `mlptf/schema/scalars.py`,
   `mlptf/schema/schema.py` (a `@strawberry.type class MlptfScalars`, copying the shape of
   `spotting/schema/schema.py`), appends `MlptfScalars` to the `Query` base list in
   `rosak/schema.py`, and adds the `badges` resolver to `UserScalar` in
   `common/schema/scalars.py` — mirroring its existing async `spottings` field, which batches through
   `info.context.loaders["common"]["spottings_from_user_loader"]`; the matching batch function would
   go in `common/schema/loaders.py` next to `batch_load_spottings_from_user` and be registered in the
   same `LOADERS` dict to avoid N+1 on user lists.

2. **Deterministic, rule-based badge awarding as a nightly Celery task.** Every signal worth awarding
   on is already in adjacent tables and needs nothing but `COUNT`/`GROUP BY`: `spotting.Event`
   filtered on `reporter_id` for volume badges, joined through `Event.vehicle` →
   `operation.Vehicle.lines` for "50 spottings on the Kelana Jaya line", diffed against the
   `operation.VehicleLine` roster for "spotted every set on this line", `Event.type` for
   type-completionist badges, and `common.User.created` for tenure badges. These are plain ORM
   predicates — no scoring, no inference — and the task shape already exists to copy:
   `spotting/tasks.py::report_spotting_today` is a `@celery_app.task(bind=True)`, and
   `rosak/celery.py` already calls `app.autodiscover_tasks()`, so a new `mlptf/tasks.py` is picked up
   automatically. Announcing new awards is also solved: `telegram_provider` is the project's live user
   channel and `report_spotting_today` already demonstrates posting via `telegram.Bot` to
   `operation.Line.telegram_channel_id`.
   **Readiness:** `Partially ready` — the data is all there, but there are two concrete blockers.
   (a) `UserBadge` has **no** `UniqueConstraint` on `(user, badge)`, so a nightly re-run would
   re-award the same badge every night; fix in `mlptf/models.py` with a `Meta.constraints` entry plus
   a new `mlptf/migrations/0002_*.py`, then use `UserBadge.objects.get_or_create` /
   `bulk_create(ignore_conflicts=True)`. (b) `Badge` has no column to anchor a rule to, so the
   rule→badge mapping needs either a new `Badge.code`/`slug` field (unique) or a code-side registry
   keyed on badge id; decide before writing the task. Also decide explicitly whether
   `Event.is_anonymous=True` rows count toward eligibility. New beat entry goes in
   `app.conf.beat_schedule` in `rosak/celery.py`.

3. **Badge rarity and holder listings.** `Badge.users` (the M2M reverse of the through-model) already
   supports `Badge.objects.annotate(holder_count=Count("users"))`, which yields "held by 3 members"
   rarity labels, a sorted badge index, and a per-badge holder list. The repo already does exactly
   this kind of aggregation in GraphQL — see `CommonScalars.medias_group_by_period` in
   `common/schema/schema.py` using `Count`/`ArrayAgg`, and `CommonScalars.medias` using
   `ListConnectionWithTotalCount` for paginated connections. Rarity is what makes a badge worth
   chasing on a hobbyist platform, and it costs one annotation.
   **Readiness:** `Not ready` — purely because there is no `mlptf` GraphQL surface to hang it on;
   it becomes a handful of lines once item 1 exists. Implementer touches
   `mlptf/schema/scalars.py` (add `holder_count`) and `mlptf/schema/schema.py` (add a `badges`
   connection). Note the counts double-count until item 2's `(user, badge)` uniqueness constraint
   lands.

4. **Scheduled and seasonal badge reveals using `Badge.released`.** `released` is a required
   `DateField` documented as the "minted on" date, and **nothing in the codebase filters on it** —
   not the resolvers (there are none) and not `BadgeAdmin`, which only puts it in `list_display` and
   `search_fields`. Treating it as a publish date turns it into a scheduling primitive: staff can
   pre-create badges for a line opening, an MLPTF anniversary or a spotting campaign, and have them
   appear on their own date via a single `filter(released__lte=date.today())` in the public resolver.
   **Readiness:** `Partially ready` — the field exists and is already populated; what is missing is
   any code that respects it. Two edits: add the `released__lte` filter in the future
   `mlptf/schema/schema.py` resolver (depends on item 1), and add `list_filter = ["released"]` plus
   `date_hierarchy = "released"` to `BadgeAdmin` in `mlptf/admin.py` so staff can see what is
   scheduled versus live. Decide whether an unreleased badge may still be awarded (it can be today,
   silently).

5. **Bring badge sprites into the project's own media pipeline.** `Badge.sprite_url` is a `URLField`,
   not a `FileField` and not an FK to `common.Media`, so every badge image lives on an unmanaged
   third-party host: nothing validates the URL still resolves, `django_cleanup` cannot garbage-collect
   it, and a dead host silently breaks every profile that displays the badge. Pointing badges at
   `common.Media` — the same model `spotting.EventMedia`, `operation.StationMedia` and
   `operation.AssetMedia` already use — puts artwork behind `common.views.GenericUpload`, gives it the
   same lifecycle as every other image in the product, and makes consistent sprite dimensions
   enforceable. (This is about *hosting and integrity* for hand-made artwork, distinct from anything
   generative.)
   **Readiness:** `Not ready` — needs a schema change and a data migration. Add
   `Badge.sprite = FK("common.Media", null=True)` alongside the existing `sprite_url` in
   `mlptf/models.py`, ship `mlptf/migrations/0002_*.py`, backfill by downloading each `sprite_url`
   into a `common.Media` row, then deprecate the `URLField` in a later migration. Keep both fields
   during the transition and have the item-1 resolver prefer `sprite` and fall back to `sprite_url`,
   since the field is currently non-nullable with no default.

## 💡 Potential AI Feature Opportunities

The app's value here is that it is a clean, unopinionated *reward sink* sitting next to several
rich activity streams. Three things it is structurally ready for:

1. **Automated / inferred badge awarding.** `UserBadge` is already an explicit through-model, so an
   eligibility engine — heuristic or model-driven — can write awards without any schema change. The
   inputs already exist in-repo: `spotting` submissions, `incident` reports, `chartography`
   snapshots. Natural first cut: a nightly Celery task (mirroring
   `chartography.tasks.aggregate_line_vehicle_status_mlptf_task`) that evaluates rules per user and
   inserts `UserBadge` rows, with an added `awarded_by`/`reason` column for auditability.
2. **Generated badge artwork and copy.** `sprite_url` and `description` are both free-form and both
   currently filled by hand. An assisted flow could draft a badge `description` from its name plus
   award criteria, and generate/route sprite artwork through the project's existing upload pipeline
   (`common.views.GenericUpload`) rather than leaving `sprite_url` pointing at unmanaged external
   hosts.
3. **Personalised contribution nudges.** Once badges are exposed on the GraphQL `User` type, the
   gap between a user's current activity and their nearest unearned badge becomes a natural
   recommendation surface — "two more sightings on this line completes X" — deliverable through the
   already-wired `telegram_provider` bot, which is the project's existing user-notification channel.

**Recommendation before any of the above:** close the basics first — add `__str__` to both models, a
`UniqueConstraint` on `UserBadge(user, badge)`, `Meta.ordering` on `Badge`, and at minimum a
read-only GraphQL exposure. Until badges are visible to the front end, this app is a write-only
admin table and any investment in awarding logic is invisible to users.

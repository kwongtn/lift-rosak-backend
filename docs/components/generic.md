# Component: generic

## 📌 Purpose & Scope

- **Core Responsibility:** A shared-primitives library app. It owns no data of its own and exposes no
  URLs, tasks or signals. It solves exactly one problem: giving the domain apps (`spotting`,
  `operation`, `incident`, `common`, `telegram_provider`, `chartography`) a single definition of
  _cross-cutting geospatial and date-bucketing primitives_ — an abstract GIS model, a lat/long
  admin form, GeoDjango ↔ GraphQL scalars, one shared enum and one shared GraphQL input.
- **Domain/Layer:** Django shared-kernel / cross-app foundation layer. It spans three layers at once:
  ORM (abstract model), Django admin presentation (form + mixin) and GraphQL schema primitives
  (Strawberry scalars/enums/inputs). It is registered in `INSTALLED_APPS`
  (`rosak/settings.py:101`) only so its abstract model is importable; it contributes **no** tables.

## 🔌 Interface & Data Flow

### Exported abstractions (the app's real public API)

| Primitive                                                                   | File                        | Kind                                                                                                                                                              |
| --------------------------------------------------------------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WebLocationModel`                                                          | `generic/models.py`         | Abstract Django GIS model (`accuracy`, `altitude`, `altitude_accuracy`, `heading`, `speed`, `location: PointField`) — mirrors the browser Geolocation API payload |
| `GeometricForm`                                                             | `generic/views.py`          | Abstract `forms.ModelForm` replacing the admin GIS map widget with `latitude`/`longitude` float fields                                                            |
| `JsonPrettifyAdminMixin`                                                    | `generic/admin.py`          | Admin mixin, `prettify_json()` → Pygments-highlighted JSON                                                                                                        |
| `DateGroupings`                                                             | `generic/schema/enums.py`   | `@strawberry.enum` — `YEAR / MONTH / WEEK / DAY`                                                                                                                  |
| `WebLocationInput`                                                          | `generic/schema/inputs.py`  | `@strawberry.input` mirroring `WebLocationModel` (flat `latitude`/`longitude`/`altitude`)                                                                         |
| `GeoPoint`, `GeoLineString`, `GeoLinearRing`, `GeoPolygon`, `GeoMultiPoint` | `generic/schema/scalars.py` | `strawberry.scalar` wrappers over `django.contrib.gis.geos` types                                                                                                 |
| `Point2D`, `GeometricSearchField`, `Point2D_SearchField`                    | `generic/types.py`          | Plain `TypedDict`s for radius search — **currently unused anywhere**                                                                                              |
| `GenericScalars`, `GenericMutations`                                        | `generic/schema/schema.py`  | Empty Strawberry query/mutation roots (see caveats)                                                                                                               |
| `PublicSpottingStats`                                                       | `generic/schema/types.py`   | Empty `@strawberry.type` stub (see caveats)                                                                                                                       |

### Inputs (GraphQL arguments / input types / form data)

- `WebLocationInput` — all seven fields typed `Optional[float]` **with no default**, so in Strawberry
  they surface as nullable-but-_required_ arguments. Consumers nevertheless test them against
  `strawberry.UNSET` (`spotting/schema/schema.py:125-155`), a branch that cannot be reached as
  declared. Flagging as an inconsistency, not fixing it here.
- `GeoPoint` scalar as an input: `parse_value=lambda v: Point(v)` turns an `(x, y[, z])` tuple into a
  GEOS `Point`. Used as an input/output field type in `operation/schema/scalars.py:26`.
- `DateGroupings` as a resolver argument, conventionally defaulted to `DateGroupings.DAY`
  (`operation/schema/scalars.py:79,305`, `common/schema/scalars.py:148`).
- `GeometricForm` receives admin POST data; `latitude` bounded ±90, `longitude` bounded ±180.

### Outputs (GraphQL types returned / events)

- Scalars serialize back out via `serialize=lambda v: v.tuple` — GeoDjango geometry → plain tuple.
- `GeometricForm.clean()` returns cleaned data with the configured `field_name` populated as a
  `Point(longitude, latitude)`; `__init__` performs the reverse (Point → initial lat/long) for
  rendering.
- No Celery tasks, no Django signals (sent or received), no `urls.py`, no REST views. `generic`
  appears nowhere in `rosak/celery.py`'s beat schedule and nowhere in `rosak/urls.py`.

### Dependencies

- `django.contrib.gis` (`models.PointField`, `geos.Point/LineString/LinearRing/Polygon/MultiPoint`)
  — implies PostGIS.
- `strawberry` / `strawberry-django` (schema is assembled in `rosak/schema.py`).
- `pygments` (`HtmlFormatter`, `JsonLexer`) for the admin JSON mixin.

### Consumers (explicit list)

- **`spotting`** — `spotting/models.py:15` `LocationEvent(WebLocationModel)`;
  `spotting/schema/inputs.py:7,22` embeds `WebLocationInput`; `spotting/admin.py:15`
  `LocationEventForm(GeometricForm)`.
- **`operation`** — `operation/admin.py:125` `StationForm(GeometricForm)`;
  `operation/schema/scalars.py:12-13,26,79,305` uses `DateGroupings` + `GeoPoint`;
  `operation/views.py:13,32,107` uses `DateGroupings`. `operation/schema/inputs.py:6` has a
  _commented-out_ `GeoPoint` import.
- **`incident`** — `incident/admin.py:40,67` `VehicleIncidentLocationForm` and
  `StationIncidentLocationForm`, both `GeometricForm` subclasses.
- **`common`** — `common/utils.py`, `common/schema/scalars.py`, `common/schema/types.py`,
  `common/schema/schema.py` all import `DateGroupings`; it drives the date-truncation/grouping
  helpers (`get_default_start_time`, grouping switch statements).
- **`telegram_provider`** — `telegram_provider/admin.py:4,9` mixes in `JsonPrettifyAdminMixin`.
- `chartography` and `reporting` do **not** import from `generic` today.

## ⚙️ Internal State & Logic

- **Stateless by design.** No models are concrete, so `generic/migrations/` contains only
  `__init__.py` — zero migrations have ever been generated for this app. Schema evolution of the
  location fields therefore lives entirely in the _consuming_ apps' migrations (e.g. `spotting`).
- The only real logic is `GeometricForm`'s bidirectional Point ↔ (lat, long) marshalling, and it is
  configured by **class attribute mutation, not inheritance**: subclasses assign
  `GeometricForm.Meta.model` / `GeometricForm.Meta.widgets` on the _parent's_ `Meta`. Because every
  subclass writes to the same shared `Meta` object, this is order-dependent global mutation and a
  latent cross-app bug if two forms are ever bound in an unexpected import order. Worth noting; not
  changed here.
- `GeometricForm.required` is `None` (falsy), so `latitude`/`longitude` end up optional regardless of
  whether the underlying `PointField` is non-nullable.
- `clean()` only builds a Point when `latitude and longitude` are both truthy — a legitimate
  `longitude == 0` (prime meridian) would be silently dropped.
- Scalars are module-level constants evaluated at import time; there is no caching or state.

## 🧩 Extension Points & Hooks

- **Abstract model inheritance** — subclass `WebLocationModel` to gain the full browser-geolocation
  field set. `spotting.LocationEvent` shows the pattern (it redundantly re-declares `location` with
  identical `blank=False, null=False`).
- **Admin form inheritance** — subclass `GeometricForm`, set `field_name` and the `Meta` overrides.
  Three apps already do this; it is the established way to add a lat/long-editable GIS model to admin.
- **Admin mixin composition** — `JsonPrettifyAdminMixin` is a plain mixin, safe to add to any
  `ModelAdmin` alongside other mixins.
- **Scalar registry** — `generic/schema/scalars.py` is the intended home for new GeoDjango↔GraphQL
  scalars. Only `GeoPoint` is consumed today; `GeoLineString`, `GeoLinearRing`, `GeoPolygon` and
  `GeoMultiPoint` are defined and ready but wired to nothing.
- **Un-wired schema root** — `GenericScalars` / `GenericMutations` exist as the conventional
  per-app Strawberry query/mutation roots, so a future `generic`-owned field has an obvious home,
  but they must first be added to `rosak/schema.py`'s `Query` / `Mutation` bases.

### Incomplete / ambiguous (stated plainly, not inferred behavior)

1. **`generic/schema/schema.py` and `generic/schema/types.py` are untracked WIP.** Both are empty
   shells: `GenericScalars` has a commented-out `public_spotting_stats` resolver and a bare `pass`;
   `GenericMutations` is `pass`; `PublicSpottingStats` has no fields. Neither is imported anywhere,
   and `rosak/schema.py` does **not** include them. A `@strawberry.type` with no fields is invalid in
   GraphQL, so wiring them in as-is would fail schema construction. Intent appears to be a public
   (unauthenticated) spotting-stats endpoint, but nothing is implemented.
2. **`generic/types.py` is dead code.** `Point2D`, `GeometricSearchField` and `Point2D_SearchField`
   have no importers; the radius-search feature they were meant to type was never built.
3. **`generic/schema/` has no `__init__.py`.** It resolves as an implicit namespace package, which
   works but is inconsistent with e.g. `spotting/schema/__init__.py`.
4. **`generic/tests.py` is empty (0 bytes).** The shared primitives used by five apps have no test
   coverage at all.

## 💡 Potential Feature Opportunities

Because `generic` owns no tables, its "features" are capabilities it would hand to the five consuming
apps, plus the correctness work that unblocks them.

1. **A typed, shared point-and-radius search input.** `operation/schema/filters.py:51-62` already does
   proximity filtering (`location__distance_lt=(Point(x, y, z), Distance(km=radius))`) but types the
   argument as an untyped `strawberry.scalars.JSON`, so a caller who omits `radius` reaches
   `Distance(km=None)` and a missing `x`/`y` reaches `Point(None, None, None)`. Promoting
   `generic/types.py`'s dead `Point2D` / `GeometricSearchField` / `Point2D_SearchField` TypedDicts into
   a real `@strawberry.input` in `generic/schema/inputs.py`, alongside a small shared `Q`-builder,
   turns one app's ad-hoc filter into a shared capability. `spotting.LocationEvent` and
   `incident.IncidentAbstractModel` both carry `PointField`s (`spotting/models.py:22`,
   `incident/models.py:26`) and expose **no** geo filtering at all today, so both gain "near me"
   queries from the same primitive.
   **Readiness:** `Ready` — no blockers. Add the input type to `generic/schema/inputs.py`, add the
   `Q`-builder next to it, then swap `StationFilter.location` in
   `/home/kwongtn/rosak_backend/operation/schema/filters.py` off `strawberry.scalars.JSON` and add
   equivalent filter fields in `spotting/schema/` and `incident/schema/`.

2. **Route and service-area geometry for `operation.Line`.** No model in the codebase declares
   anything other than a `PointField` (only `operation/models.py:90`, `incident/models.py:26`,
   `spotting/models.py:22`), yet `GeoLineString`, `GeoLinearRing`, `GeoPolygon` and `GeoMultiPoint`
   sit fully implemented and unused in `generic/schema/scalars.py`. Giving `operation.Line` a
   `LineStringField` for its alignment and exposing it through `GeoLineString` on the existing
   `Line` GraphQL type (`operation/schema/scalars.py:39`) lets a client draw real routes instead of
   interpolating between station points, and a `GeoPolygon` filter argument gives deterministic
   bounding-box / corridor queries ("everything inside this map viewport") for `spotting` and
   `incident` via PostGIS `__within` / `__intersects`.
   **Readiness:** `Partially ready` — `GeoMultiPoint` now correctly uses `NewType("GeoMultiPoint", ...)` in `generic/schema/scalars.py`. Add the model field plus migration in `operation/`.

3. **A `GeometricForm` that is safe to reuse, unblocking further GIS admin screens.** All four
   subclasses — `spotting/admin.py:15`, `operation/admin.py:125`, `incident/admin.py:40` and
   `incident/admin.py:67` — configure the form by assigning to the **parent's** shared
   `GeometricForm.Meta`. `incident` sets `GeometricForm.Meta.widgets = {"location":
forms.HiddenInput()}` while `spotting` and `operation` deliberately comment that line out, so
   whether the `location` field renders hidden in the spotting and station admin depends purely on
   module import order. Separately, `required = False` on each subclass is dead code: `latitude` and
   `longitude` are constructed in `GeometricForm`'s own class body with `required=required` while
   `required` is still `None`, so the subclass value is never read. Fixing both makes adding a fifth
   GIS admin form (e.g. geotagged `common.Media`, or further `incident` subtypes) a safe, one-class
   operation instead of a cross-app hazard.
   **Readiness:** `Ready` — contained to `/home/kwongtn/rosak_backend/generic/views.py` plus one-line
   edits in the four subclasses. Move model/widget configuration into per-subclass `Meta` classes (or
   an `__init_subclass__` hook), and build the `latitude`/`longitude` fields inside `__init__` from
   `self.required` so the subclass override takes effect.

4. **Validation parity between the GraphQL ingestion path and the admin path.** The admin form bounds
   coordinates (`latitude` ±90, `longitude` ±180 in `generic/views.py:23-32`), but the mutation path
   does not: `spotting/schema/schema.py:148` builds `Point(x=location_input.longitude,
y=location_input.latitude)` straight from `WebLocationInput` with no range check, so a client can
   persist a `LocationEvent` at latitude 500. Adding a `clean()` (or `Meta.constraints`) on
   `WebLocationModel` — coordinate bounds, `accuracy` within a configured metre tolerance, and
   optionally a great-circle-distance ÷ elapsed-time check against a reporter's previous
   `LocationEvent` to reject physically impossible jumps — is plain arithmetic and gives every current
   and future `WebLocationModel` subclass the same guarantees for free. `generic/views.py`'s
   `clean()` should be corrected in the same pass: its `if latitude and longitude` guard silently
   discards a legitimate `longitude == 0`.
   **Readiness:** `Partially ready` — two blockers. First, `WebLocationInput`
   (`generic/schema/inputs.py`) declares all seven fields as `Optional[float]` with **no default**,
   which Strawberry renders as nullable-but-_required_ arguments, making the `strawberry.UNSET`
   branches at `spotting/schema/schema.py:125-153` unreachable; give each field
   `= strawberry.UNSET` so partial submissions and per-field validation both become expressible.
   Second, `generic/tests.py` is 0 bytes, so there is no harness to prove new validation rules do not
   break the five consuming apps — add tests there before changing shared `clean()` behaviour.

5. **`QUARTER` and `HOUR` members for `DateGroupings`.** `DateGroupings`
   (`generic/schema/enums.py`) is the single bucketing vocabulary for every analytics resolver in
   `common` and `operation`, and it stops at `DAY`. `HOUR` would enable time-of-day spotting
   distribution charts; `QUARTER` would enable quarterly reporting — both directly on the existing
   `get_trends` aggregation helper, with no new query surface. The enum is a closed exhaustive switch
   (`common/utils.py:88-105` and `:64-81` both `raise RuntimeError` on an unknown member), so the
   blast radius is precisely known.
   **Readiness:** `Partially ready` — `get_default_start_time()` is fixed (uses `date.replace()`). Add the enum members and their arms in `get_default_start_time()`, `get_group_strs()` (`common/utils.py:84-105`), the `display_year` / `display_month` / `display_week` lists (`common/utils.py:162-170`) and the `date_group == DateGroupings.WEEK` check at `common/utils.py:286`.

## 💡 Potential AI Feature Opportunities

1. **Geospatial anomaly / plausibility scoring on location submissions.** `WebLocationModel` already
   captures `accuracy`, `altitude`, `heading` and `speed` alongside the point — exactly the feature
   vector needed to score a submitted spotting location for plausibility (impossible speed between
   consecutive sightings, accuracy far outside tolerance, heading inconsistent with the rail
   corridor). The abstract model is the natural place to hang a computed confidence field, and every
   consumer inherits it for free.
2. **Radius / corridor search resolvers.** The unused `Point2D_SearchField` TypedDict plus the
   already-defined `GeoPolygon` / `GeoLineString` scalars mean a "sightings near me" or "sightings
   along this line" GraphQL query is a thin resolver away — and that same primitive underpins natural
   language geo queries ("show me spottings within 2 km of KL Sentral last week") by mapping an LLM's
   extracted intent onto `GeoPoint` + radius + `DateGroupings`.
3. **Natural-language time bucketing.** `DateGroupings` is the single vocabulary every analytics
   resolver in `common` and `operation` already speaks. An LLM layer that translates a free-text
   request into a `(DateGroupings, start, end)` triple could drive the existing aggregation helpers
   without any new query surface — the enum is deliberately small and closed, which makes it a safe
   constrained output target.

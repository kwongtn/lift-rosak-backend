# Component: generic

## 📌 Purpose & Scope

- **Core Responsibility:** Shared primitives for the domain apps: an abstract GIS model, a lat/long admin form, GeoDjango ↔ GraphQL scalars, the `DateGroupings` enum, the `WebLocationInput` GraphQL input and a JSON-pretty admin mixin. It owns no tables, URLs, tasks or signals.
- **Domain/Layer:** Shared kernel spanning ORM (abstract model), Django admin (form + mixin) and GraphQL primitives (scalars, enum, input). Listed in `INSTALLED_APPS` (`rosak/settings.py`) so its abstract model is importable. It contributes **no** tables and zero migrations (`generic/migrations/` holds only `__init__.py`).

## 🔌 Interface & Data Flow

### Exported abstractions

| Primitive | File | Kind |
| --- | --- | --- |
| `WebLocationModel` | `generic/models.py` | Abstract GIS model: `accuracy`, `altitude`, `altitude_accuracy`, `heading`, `speed` (nullable Decimals) + `location: PointField` (non-null). Mirrors the browser Geolocation payload. |
| `GeometricForm` | `generic/views.py` | Abstract `ModelForm` replacing the admin GIS map widget with `latitude` / `longitude` float fields. |
| `JsonPrettifyAdminMixin` | `generic/admin.py` | `prettify_json()` returns Pygments-highlighted JSON. |
| `DateGroupings` | `generic/schema/enums.py` | `@strawberry.enum` `YEAR / MONTH / WEEK / DAY`. |
| `WebLocationInput` | `generic/schema/inputs.py` | `@strawberry.input`, seven flat fields (`latitude`, `longitude`, `altitude`, `accuracy`, `altitude_accuracy`, `heading`, `speed`), each `Maybe[float \| None] = UNSET`. |
| `GeoPoint`, `GeoLineString`, `GeoLinearRing`, `GeoPolygon`, `GeoMultiPoint` | `generic/schema/scalars.py` | `strawberry.scalar` wrappers over `django.contrib.gis.geos`. `parse_value` builds the geometry, `serialize` returns `.tuple`. |
| `Point2D`, `GeometricSearchField`, `Point2D_SearchField` | `generic/types.py` | Plain `TypedDict`s. **Unused** (see Incomplete). |

### Inputs

- `WebLocationInput`: every field defaults to `UNSET`; explicit `null` arrives as `Some(None)`. Embedded by `spotting/schema/inputs.py`.
- `GeoPoint` as input: `parse_value` turns an `(x, y[, z])` tuple into a GEOS `Point`. Consumed by `operation/schema/scalars.py` (`Station.location: Optional["GeoPoint"]`).
- `DateGroupings` as a resolver argument, conventionally defaulted to `DAY` (`operation`, `common` schema modules).
- `GeometricForm` receives admin POST data. `latitude` is bounded to ±90, `longitude` to ±180.

### Outputs

- Scalars serialize as `value.tuple`.
- `GeometricForm.clean()` writes `Point(longitude, latitude)` into `field_name`. `__init__` does the reverse (existing `Point` → initial lat/long) for rendering.
- No Celery tasks, signals, `urls.py` or REST views. `generic` appears in neither `rosak/celery.py` nor `rosak/urls.py`, and it contributes no root to `rosak/schema.py`.

### Dependencies

- `django.contrib.gis` (`PointField`, `geos` types), which implies PostGIS.
- `strawberry` (the schema is assembled in `rosak/schema.py`).
- `pygments` (`HtmlFormatter`, `JsonLexer`) for the admin mixin.
- Imports nothing first-party.

### Consumers

- **`spotting`**: `models.py` `LocationEvent(WebLocationModel)`; `admin.py` `LocationEventForm(GeometricForm)`; `schema/inputs.py` embeds `WebLocationInput`.
- **`operation`**: `admin.py` `StationForm(GeometricForm)`; `schema/scalars.py` uses `DateGroupings` and `GeoPoint`; `views.py` uses `DateGroupings`.
- **`incident`**: `admin.py` `VehicleIncidentLocationForm` and `StationIncidentLocationForm`, both `GeometricForm` subclasses.
- **`common`**: `DateGroupings` in `utils.py` (date-truncation and grouping helpers), `schema/scalars.py`, `schema/types.py`, `schema/schema.py`.
- **`telegram_provider`**: `admin.py` mixes in `JsonPrettifyAdminMixin`.
- `chartography` and `reporting` do not import from `generic`.

## ⚙️ Internal State & Logic

- **Stateless.** No concrete models. Scalars are module-level constants built at import, and nothing is cached.
- **`GeometricForm` is the only real logic** (bidirectional Point ↔ lat/long). It is configured by **mutating the parent's shared `GeometricForm.Meta`**, not by inheritance. Each subclass assigns `GeometricForm.Meta.model` / `.widgets` on the same object, which is order-dependent global state across apps. Current widget state: `incident/admin.py` hides `location`; `spotting/admin.py` and `operation/admin.py` have that line commented out, so rendering depends on import order (MISTAKES.md, 2026-08-24 generic).
- **`required` is dead.** `required: bool = None`, and `latitude` / `longitude` are built in the class body while it is still `None`. The `required = False` lines in subclasses are never read.
- **`clean()` drops `longitude == 0`.** It builds a Point only when `latitude and longitude` are truthy, so the prime meridian is silently discarded. The fix is an `is not None` test.

## 🧩 Extension Points & Hooks

- **Abstract model inheritance.** Subclass `WebLocationModel` to get the browser-geolocation field set. `spotting.LocationEvent` re-declares `location` with identical options (redundant, harmless).
- **Admin form inheritance.** Subclass `GeometricForm`, set `field_name` and the `Meta` overrides. Three apps already do this, and it is the established way to make a GIS model lat/long-editable in admin. Mind the shared-`Meta` caveat above.
- **Admin mixin.** `JsonPrettifyAdminMixin` composes with any `ModelAdmin`.
- **Scalar registry.** `generic/schema/scalars.py` is the home for new GeoDjango ↔ GraphQL scalars. Only `GeoPoint` is consumed today.
- **Enum.** `DateGroupings` is the single bucketing vocabulary. A new member needs arms in `common/utils.py` (see Feature 5).
- **No generic schema root exists.** A generic-owned GraphQL field needs a new `generic/schema/schema.py` mixin appended to `rosak/schema.py`'s `Query` bases.

### Incomplete / ambiguous

1. **`generic/types.py` is dead code.** `Point2D`, `GeometricSearchField` and `Point2D_SearchField` have no importers. The radius search they were meant to type is unbuilt (Feature 1).
2. **Non-point scalars are unused.** `GeoLineString`, `GeoLinearRing`, `GeoPolygon` and `GeoMultiPoint` have no consumers outside `generic/tests.py`. No model declares a non-point geometry (Feature 2).
3. **`generic/schema/` has no `__init__.py`.** It resolves as an implicit namespace package, which works but is inconsistent with other apps.
4. **Partial test coverage.** `generic/tests.py` covers `GeoPoint` / `GeoLineString` parse and serialize, and `WebLocationInput` UNSET / null semantics. `GeometricForm`, `JsonPrettifyAdminMixin` and `DateGroupings` have no direct tests.

## 💡 Potential Feature Opportunities

1. **Typed shared point-and-radius search input.** `operation/schema/filters.py` (`StationFilter.location`, around lines 51-62) types its argument as `strawberry.scalars.JSON`. A caller who omits `radius` reaches `Distance(km=None)`. Promoting `Point2D_SearchField` into a `@strawberry.input` in `generic/schema/inputs.py`, with a shared `Q`-builder, gives `spotting.LocationEvent` and `incident.IncidentAbstractModel` "near me" filtering. Both carry `PointField`s and expose no geo filter today.
   **Readiness:** `Ready`. Add the input type and builder, swap `StationFilter.location` off JSON, add filter fields in `spotting/schema/` and `incident/schema/`.

2. **Route and service-area geometry for `operation.Line`.** No model declares anything but a `PointField`, so the unused `GeoLineString` / `GeoPolygon` / `GeoMultiPoint` scalars have nothing to serialize. A `LineStringField` on `operation.Line` exposed through `GeoLineString` lets clients draw real routes. A `GeoPolygon` argument enables viewport and corridor queries (`__within` / `__intersects`) for `spotting` and `incident`.
   **Readiness:** `Partially ready`. The model field and migration in `operation/` are still needed.

3. **A `GeometricForm` that is safe to reuse.** Fix the shared-`Meta` mutation (per-subclass `Meta` or an `__init_subclass__` hook) and build the `latitude` / `longitude` fields in `__init__` from `self.required`, so the subclass override takes effect. Four subclasses are affected: `spotting/admin.py`, `operation/admin.py`, `incident/admin.py` (two).
   **Readiness:** `Ready`. Contained to `generic/views.py` plus one-line edits in the subclasses. Makes a fifth GIS admin form (for example geotagged `common.Media`) a one-class change.

4. **Validation parity between GraphQL ingestion and admin.** The admin form bounds coordinates, but the mutation path does not. `spotting/schema/schema.py` builds `Point(x=longitude, y=latitude)` from `WebLocationInput` with no range check, so a client can persist a `LocationEvent` at latitude 500. Add `clean()` or `Meta.constraints` on `WebLocationModel` covering coordinate bounds and `accuracy` tolerance. An optional great-circle-distance ÷ elapsed-time check would reject impossible jumps. Also fix the `longitude == 0` guard in `GeometricForm.clean()`.
   **Readiness:** `Ready`. Add tests for `GeometricForm.clean()` and the spotting mutation path before changing shared validation, because nothing covers them today.

5. **`QUARTER` and `HOUR` members for `DateGroupings`.** `HOUR` enables time-of-day spotting charts, and `QUARTER` enables quarterly reports. `DateGroupings` is closed: `get_default_start_time()` and `get_group_strs()` in `common/utils.py` raise `RuntimeError` on unknown members, and the `display_*` flags and the `DateGroupings.WEEK` check in the same module need arms too. The blast radius is known.
   **Readiness:** `Ready`.

## 💡 Potential AI Feature Opportunities

1. **Geospatial plausibility scoring on submissions.** `WebLocationModel` already stores `accuracy`, `altitude`, `heading` and `speed` beside the point. That is enough to score impossible speed between sightings, accuracy outside tolerance, or heading inconsistent with the rail corridor. A computed confidence field on the abstract model would reach every consumer.
2. **Radius and corridor search from natural language.** Once Feature 1 exists, an LLM's extracted intent ("within 2 km of KL Sentral last week") maps onto `GeoPoint`, a radius and a `DateGroupings` value.
3. **Natural-language time bucketing.** `DateGroupings` is a small, closed vocabulary, which makes it a safe constrained output target for turning free text into `(DateGroupings, start, end)` for the existing aggregation helpers.

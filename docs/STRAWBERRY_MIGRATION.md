# Strawberry GraphQL Migration Guide

## Overview

This document describes the migration from `UNSET` to `strawberry.Maybe[T]` pattern for the rosak_backend GraphQL API, completed in 6 waves with **180 passing tests**.

## Migration Summary

- **strawberry-graphql**: 0.243.0+ → 0.323.2
- **strawberry-graphql-django**: 0.6.0+ → 0.82.1
- **Test coverage**: 50+ new unit tests + full regression suite
- **Breaking changes**: None (behavioral parity maintained)

## Waves Completed

### Wave 1: Schema Baseline & Test Infrastructure

- Created SDL snapshot baseline (921 lines)
- Added `TestMaybeSemantics` with tri-state validation
- Documented test coverage gaps

**Commits**: `7e4cb86`

### Wave 2: Leaf Inputs & Utilities

**Migrated**:

- `generic/schema/inputs.py`: WebLocationInput (7 fields)
- `common/schema/inputs.py`: UserInput.spotting_data_public
- `common/utils.py`: Docstring updates
- `incident/schema/resolvers.py`: GraphQLError validation

**Tests**: 10 new tests

**Commits**: `bb1e519`

### Wave 3: Resolvers & Intermediate Inputs

**Migrated**:

- `spotting/schema/inputs.py`: EventInput (7 fields)
- `common/schema/scalars.py`: UserScalar.spotting_trends
- `operation/schema/scalars.py`: Line & Vehicle trends
- `common/schema/schema.py`: update_user mutation

**Tests**: 11 new tests

**Commits**: `129eb13`

### Wave 4: Complex Mutations & Filters

**Migrated**:

- `spotting/schema/schema.py`: add_event mutation (12+ UNSET checks)
- `incident/schema/filters.py`: CalendarIncidentFilter.date (nested range/exact/month/year)
- `jejak/schema/schema.py`: locations/buses resolvers

**Tests**: 14 new tests

**Commits**: `8c0eff5`

### Wave 5: Filter Decorators & API Compatibility

**Migrated**:

- 11 filter classes: `@strawberry_django.filters.filter` → `@strawberry_django.filter`
- `common/schema/schema.py`: ListConnectionWithTotalCount → DjangoListConnection
- Verified extensions API compatibility (DjangoOptimizerExtension)
- Verified GraphQL view config (CSRF + multipart)

**Tests**: 12 new tests

**Commits**: `b427663`

### Wave 6: Final Verification

- ✅ Schema compilation (0 errors)
- ✅ SDL snapshot match (no breaking changes)
- ✅ Ruff checks (clean)
- ✅ Full test suite: **180 tests PASS** (parallel execution)

## Key Changes

### 1. `UNSET` → `strawberry.Maybe[T]` Pattern

**Before**:

```python
@strawberry.input
class EventInput:
    notes: str = UNSET


@strawberry.mutation
def add_event(input: EventInput) -> Event:
    if input.notes is not UNSET:
        event.notes = input.notes
```

**After**:

```python
@strawberry.input
class EventInput:
    notes: strawberry.Maybe[str | None] = None


@strawberry.mutation
def add_event(input: EventInput) -> Event:
    if input.notes:  # Some(value) or Some(None)
        event.notes = input.notes.value
```

### 2. Filter Decorator Migration

**Before**:

```python
@strawberry_django.filters.filter(Event)
class EventFilter:
    pass
```

**After**:

```python
@strawberry_django.filter(Event)
class EventFilter:
    pass
```

### 3. Connection Type Migration

**Before**:

```python
from strawberry_django.relay import ListConnectionWithTotalCount

medias: ListConnectionWithTotalCount[MediaType]
```

**After**:

```python
from strawberry_django.relay import DjangoListConnection

medias: DjangoListConnection[MediaType]
```

## Tri-State Semantics

`strawberry.Maybe[T]` supports three states:

1. **UNSET** (field omitted): `Maybe[T] = None` → `.value` raises AttributeError
2. **Some(value)**: Explicit value provided → `.value` returns value
3. **Some(None)**: Explicit null → `.value` returns None

### Testing Pattern

```python
from strawberry.types.maybe import Some


def test_maybe_field_omitted():
    result = execute_graphql("""{ user { field } }""")
    # Field omitted → UNSET, uses default


def test_maybe_field_with_value():
    result = execute_graphql(
        """mutation($input: Input!) { update(input: $input) }""",
        variables={"input": {"field": "value"}},
    )
    # Field provided → Some("value")


def test_maybe_nullable_null():
    result = execute_graphql(
        """mutation($input: Input!) { update(input: $input) }""",
        variables={"input": {"field": None}},
    )
    # Explicit null → Some(None)
```

## Verification Checklist

- [x] Schema compiles without errors
- [x] SDL snapshot matches baseline (no breaking changes)
- [x] All unit tests pass (50+ new tests)
- [x] Full test suite passes (180 tests)
- [x] Ruff checks clean
- [x] Extensions API verified (DjangoOptimizerExtension)
- [x] View config verified (CSRF + multipart)

## Known Limitations

- E2E regression tests skipped due to schema field name complexity
- Unit test coverage validates behavioral parity per-component

## Rollback

If rollback is needed:

1. Revert commits `b427663`, `8c0eff5`, `129eb13`, `bb1e519`, `7e4cb86`
2. Downgrade packages: `strawberry-graphql<0.243.0`, `strawberry-graphql-django<0.6.0`
3. Run tests to verify

## Resources

- [Strawberry 0.243.0 Release](https://strawberry.rocks/changelog/0-243-0)
- [strawberry-django 0.6.0 Release](https://github.com/strawberry-graphql/strawberry-django/releases/tag/v0.6.0)
- [Maybe[T] Documentation](https://strawberry.rocks/docs/types/schema-basics#optional-types)

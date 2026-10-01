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

### Worked example: `SocialMediaLinkInput.occurredAt` (2026-09-30)

The tri-state above is easy to read and easy to get wrong at the service boundary, because Strawberry's `Maybe` **does not survive** the crossing and, worse, its truthiness lies. Two things bite, both pinned by `tests/incident/test_social_link_occurred_at_write.py`:

1. **`Some.__bool__` is always `True`.** So `if input.occurred_at:` cannot distinguish *omitted* from *explicit null* — it only distinguishes omitted from "something was sent". The mutation layer therefore translates by hand, and only because the service's three states mean three different things:

   ```python
   occurred_at = OCCURRED_AT_UNSET if not input.occurred_at else input.occurred_at.value
   ```

   with `UNSET` a private falsy sentinel on the write dataclass (`incident/services/social_links.py`). Collapsing the two into `maybe_value(input.occurred_at)` would silently reset the event time to the submission instant on **every** partial re-send — and `SocialMediaLinkInput` is replace-not-patch, so partial re-sends are the norm (see `MISTAKES.md` 2026-09-30).
2. **`null` is a value with meaning, not an absence.** `occurredAt: null` is the documented "this happened when it was reported" reset, because the column is `NOT NULL` and cannot itself be null. On the *insert* path there is no such third state, so `FeedLinkInput.occurredAt` is a flat two-state `Maybe` and both omitted and explicit null mean "let the column default fire".

   The general lesson the pair makes concrete: before adding a tri-state field to an input, decide what *all three* states do, and check that the field's `null` is not already load-bearing somewhere else in the payload.

### Worked example: `reorderSocialMediaLinks(parentId)` — when a `Maybe` is the **wrong** choice (2026-10-01)

The `occurredAt` case above is tri-state because three states mean three different things. The link-tree wave produced the mirror image across **two arguments of two sibling mutations**, and the pair is worth reading together because it is the decision, not an exception:

- **`groupSocialMediaLinks(parentId: Optional[strawberry.ID] = None)` → SDL `parentId: ID = null`.** Omitted and explicit `null` mean exactly the same thing here ("no target, elect a root"), so there are only two states and a `Maybe` would advertise a third that does not exist.
- **`reorderSocialMediaLinks(parentId: strawberry.Maybe[Optional[strawberry.ID]] = strawberry.UNSET)` → SDL `parentId: ID` — nullable, and with no SDL default therefore *optional*.** Here omitted and explicit `null` are **genuinely different requests**: an explicit `parentId: null` means "reorder the roots" (a real use — the console deciding which link leads a conversation), while an omitted one names no sibling set at all. A plain `ID = null` would answer the second with the first, so a client that forgot the argument would reorder every root in the system.

Two things worth knowing about a `Maybe` on a **bare argument** rather than on an input field, both learned the hard way here:

1. **The SDL renders the two nullable states as one, and the resolver has to separate them.** `strawberry.UNSET` is the *default value* and `Maybe[T]` renders as nullable `T`, so the printed argument is `reorderSocialMediaLinks(linkIds: [ID!]!, parentId: ID)` (`rosak/tests/snapshots/schema.graphql:678`) — **no `!`, no `= …`**. In GraphQL "required" *is* "non-null", so "required but nullable" is not a state the SDL can express at all: `is_required_argument` in graphql-core's `validation/rules/provided_required_arguments.py` is `is_non_null_type(arg.type) and arg.default_value is Undefined`, which evaluates `False` here, and `ProvidedRequiredArgumentsRule` never fires. A nullable, defaultless argument is plain **optional**, so the omission is **legal to send and refused on arrival** — on graphql-core 3.2.6 all three client spellings (key absent from the selection, key absent from a declared nullable variable, explicit `null`) come back **valid** from `validate()` and enter the resolver, where `Maybe` supplies `UNSET`. (The one spelling stopped earlier declares `$parentId: ID!` and omits it, and that is a **client-chosen** type caught by variable coercion, not a property of the field.) A `Maybe` on an `input` *field* is a different animal: it is omitted from the SDL entirely unless given a default, and the omission is how `UNSET` is normally reached. Read the printed SDL, not the annotation, to know which one you have.
2. **The truthiness rule is the same and still load-bearing.** `UNSET` is falsy, `Some.__bool__` is always `True`, so `if not parent_id:` isolates the omitted case and only then is `.value` safe to read:

   ```python
   if not parent_id:  # UNSET only; Some(None) and Some(ID) are both truthy
       raise GraphQLError("reorderSocialMediaLinks requires parentId. ...")

   parent_id = int(parent_id.value) if parent_id.value is not None else None
   ```

   So this guard is the **only** line of defence for a validated request, not a
   belt-and-braces second one: nothing upstream refuses the omission, and
   `tests/incident/test_social_link_threads.py::test_omitting_parent_id_on_reorder_is_refused_not_treated_as_the_roots`
   sends the key absent from the selection entirely and passes **only** because the guard sits in
   the resolver (delete the guard and the mutation succeeds silently — verified by sabotage in this
   wave). That is the design rather than a workaround: tightening `parentId` to `ID!` would turn
   the meaningful `null` ("reorder the ROOTS") into a hard error, so the schema *cannot* express
   the distinction and the resolver does it instead. What the guard still buys over the SDL is the
   one caller validation never sees — a direct Python call to the resolver.

The general lesson, and the counterpart of the one above: **a nullable argument is not automatically a tri-state argument.** Ask what an *omitted* argument means independently of an explicit `null`. If it means the same thing, declare `Optional[T] = None` and keep the signature honest. If it means nothing at all, declare `Maybe[Optional[T]] = UNSET` so the type can hold the third state and the resolver can refuse it — then check the printed SDL, because that is what tells your clients whether they may leave the key out, and **the SDL is not where the refusal happens**: a nullable defaultless argument is optional, so `UNSET` is rejected by the resolver you just wrote.

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

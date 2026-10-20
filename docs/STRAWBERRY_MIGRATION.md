# Strawberry `Maybe[T]` — Tri-State Input Semantics

Optional GraphQL inputs use `strawberry.Maybe[T]`, not the old `UNSET` sentinel
checks. Versions are pinned in [techstack.md](../techstack.md). Rules for agents live in
[AGENTS.md](../AGENTS.md); this file holds the semantics and the traps.

## The three states

| Client sends | Python value                           | Truthy? | `.value`       |
| ------------ | -------------------------------------- | ------- | -------------- |
| key omitted  | default (`strawberry.UNSET` or `None`) | no      | do not read it |
| `field: "x"` | `Some("x")`                            | yes     | `"x"`          |
| `field: null`| `Some(None)`                           | yes     | `None`         |

- **`Some.__bool__` is always `True`.** `if input.field:` separates *omitted* from
  *something was sent* and nothing else. Check truthiness first, then read `.value`.
- Declare `Maybe[T | None]` to accept an explicit `null`. Plain `Maybe[T]` rejects it
  (`Field of type 'Maybe[datetime]' cannot be explicitly set to null`).
- House style on input fields is `Maybe[T | None] = strawberry.UNSET` (`spotting`,
  `incident`, `common`); `jejak` arguments use `= None`.
- Unwrap helper: `maybe_value(field, default=None)` in
  `incident/schema/mutations/shared.py` (copy in `spotting/schema/schema.py`). Returns
  `default` when omitted, else `.value` (so explicit null comes back as `None`). Only use it
  where omitted and null mean the same thing.

## Other Strawberry API conventions in this repo

- Filters: `@strawberry_django.filter(Model)`, not `@strawberry_django.filters.filter`.
  strawberry-django 0.82.x emits a `DeprecationWarning` pointing at `filter_type`; the
  codebase has not adopted it yet.
- Connections: `strawberry_django.relay.DjangoListConnection`, not
  `ListConnectionWithTotalCount` (pinned by `common/tests.py::TestDjangoListConnection`).
- String filters: `StrFilterLookup`, not `FilterLookup[str]` (the latter produces
  `DuplicatedTypeName` warnings).

## Decide all three states before adding a field

### Tri-state: `SocialMediaLinkInput.occurredAt`

Three states, three meanings: omitted leaves the stored value alone, a value sets it,
`null` resets it to `created` ("happened when it was reported"; the column is `NOT NULL`
so it cannot hold null itself). Because `Some` is always truthy, the mutation layer
translates by hand and keeps omitted as a private falsy sentinel the service understands:

```python
occurred_at = OCCURRED_AT_UNSET if not input.occurred_at else input.occurred_at.value
```

(`UNSET` sentinel: `incident/services/social_links.py`.) Collapsing both into
`maybe_value(input.occurred_at)` would reset the event time on every partial re-send, and
`SocialMediaLinkInput` is **replace-not-patch**, so partial re-sends are normal. On the
insert-only path `FeedLinkInput.occurredAt` is two-state: omitted and `null` both let the
column default fire. Pinned by `tests/incident/test_social_link_occurred_at_write.py`.

### A `Maybe` on a bare argument: `reorderSocialMediaLinks(parentId)`

Omitted and `null` mean different things here: `parentId: null` = "reorder the roots",
omitted = "no sibling set named". So the argument is
`strawberry.Maybe[Optional[strawberry.ID]] = strawberry.UNSET`. The sibling mutation
`groupSocialMediaLinks(parentId: Optional[strawberry.ID] = None)` is a plain optional,
because omitted and `null` mean the same ("elect a root").

- **The SDL cannot express "required but nullable".** The printed argument is
  `parentId: ID` (see `rosak/tests/snapshots/schema.graphql`): nullable, no default, so
  optional. graphql-core's `is_required_argument` needs non-null *and* no default, so
  validation never refuses the omission. On graphql-core 3.2.6 all three client spellings
  (key absent, nullable variable absent, explicit `null`) validate and reach the resolver.
- **The resolver guard is the only defence.** `UNSET` is falsy, so
  `if not parent_id: raise GraphQLError(...)` isolates the omitted case; only then read
  `parent_id.value`. Tightening to `ID!` would turn the meaningful `null` into an error.
  Pinned by `test_omitting_parent_id_on_reorder_is_refused_not_treated_as_the_roots`
  in `tests/incident/test_social_link_threads.py` (it fails if the guard is removed).
- On an `input` *field* (not an argument) a `Maybe` is omitted from the SDL unless it has a
  default. Read the printed SDL, not the annotation.

**Rule of thumb:** a nullable argument is not automatically tri-state. Ask what *omitted*
means independently of `null`. Same meaning: `Optional[T] = None`. Different, or omission
must be refused: `Maybe[Optional[T]] = UNSET`, and refuse it in the resolver. Also check
the field's `null` is not already load-bearing elsewhere in the payload.

## Testing pattern

- `rosak/tests/test_schema.py::assert_maybe_field_behavior(input_class, field_name,
  test_cases)` builds a throwaway schema and asserts the parsed value for each
  `(variables, expected)` pair, e.g. `({"nickname": "t"}, UNSET)` and
  `({"nickname": "t", "spottingDataPublic": None}, Some(None))`. Examples in
  `common/tests.py::UserPrivacyTests`.
- `execute_graphql` / `execute_graphql_async` in the same module run full queries.
- Always cover omitted, value, and explicit null (`from strawberry.types.maybe import Some`).

Reference: [Maybe[T] docs](https://strawberry.rocks/docs/types/schema-basics#optional-types).

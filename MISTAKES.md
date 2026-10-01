# MISTAKES.md — rosak_backend Known Defects & Traps

> Catalog of known defects, traps and cross-component gaps so future agents don't repeat them.
> Entries use **Problem** / **Root Cause** / **Fix** / **Prevention**; fixed items carry a fix commit.
> Squashed **2026-09-30** (previous compaction `f30c313`, 2026-09-15): entries sharing a root cause are
> merged into one entry with a bullet per case, narratives are cut to the actionable rule, and fully
> historical fixes are one-liners under `## Fixed`. Earlier detail lives in `git log -p -- MISTAKES.md`.
> Dates are catalogue dates unless a fix commit is shown.

---

## Traps

### [2026-10-01] incident: `tree_queries` puts its loop protection in `clean()`, so a plain `save()` writes a **silent cycle no tree query can reach**

**Problem**: `django-tree-queries` rejects a cycle in `TreeNode.clean()`, which is only ever run by `full_clean()`. Nothing in the ORM calls it: `link.parent = other; link.save()` writes the cycle with no error, and the damage is not cosmetic. The library's recursive CTE anchors on `parent_id IS NULL`, so a node inside a cycle is unreachable from **every** tree query — `descendants()`, `ancestors()`, the loader's subtree fetch all return nothing for it — while it still sits in the table; worse, `ancestors()` *on* the cycled node raises `DoesNotExist` rather than returning `[]`, i.e. a 500 where an empty list would be the honest answer. There is no repair path in the API, only a hand-written `UPDATE`. The sibling lesson is that `full_clean()` is easy to forget *precisely because nothing forces it*: a `save()` with no `full_clean()` is ordinary Django code, so the cycle reads as a working write.
**Root Cause**: A cross-row invariant is not expressible as a row `CHECK`, and the library chose the framework hook Django itself treats as opt-in. Its answer is only as strong as the caller's discipline, and no default caller has it.
**Fix**: `SocialMediaLink.save()` runs `_guard_tree_cycle` **before** `super().save()` and raises `django.core.exceptions.ValidationError` — the same type `TreeNode.clean()` raises, so a caller already handling `full_clean()` needs no new `except`; deliberately *not* `IncidentServiceError`, which a model cannot import without a cycle, and a bare `assert` is stripped under `python -O`. The degenerate self-parent case is caught up front, because the ancestor walk cannot see it (a node is not its own ancestor) and it is just as fatal to the CTE. `full_clean()` is not called instead: it would re-validate every unrelated field on every save, and the library's own `clean()` still runs for any caller that does opt in, so the guard is additive. The check is skipped when `update_fields` is passed without `parent` — and **both** of the field's spellings count, because Django accepts a field's `name` **or** its `attname` in `update_fields` and matches on either (`Options._non_pk_concrete_field_names` puts both in one allowlist set; `Model._save_table` keeps a field on `f.name in update_fields or f.attname in update_fields`). Matching `"parent"` alone was a live hole: `save(update_fields=["parent_id"])` writes the `parent` column with the guard returned early, verified in-container by intercepting `Model._do_update` — the emitted UPDATE carried `['modified', 'parent']` and no `ValidationError` was raised. Both spellings are therefore matched, and `telegram_provider.handlers`'s `save(update_fields=["status"])` still skips the two-query walk. `bulk_create`/`bulk_update` bypass `save()` entirely, so `services/social_link_threads.py::_assert_no_cycle` re-checks before any write. Pinned by `tests/incident/test_social_link_tree_model.py::TreeCycleGuardTests`.
**Prevention**: Enforce a cross-row invariant in `save()`, not `clean()`, on any model that nests rows through a self-FK. Never assume a library's loop protection is active — read whether it lives in `clean()`, in a constraint, or nowhere. When a guard is genuinely two queries per write, scope it to the field that can actually create the violation, and say which caller the scoping is for. When that scope is expressed by matching a string in `update_fields`, match **every** spelling the API accepts — a field's name and its attname are both valid, and Django does not warn when a caller picks the other one.

### [2026-10-01] incident: `tree_path` is a recursive-CTE **annotation**, not a column — five ORM idioms that are correct elsewhere break on it

**Problem**: `django-tree-queries` stores nothing: `tree_path` / `tree_depth` / `tree_ordering` are computed per query by a CTE the library prepends to the statement. Five consequences, each of which looks like a typo rather than a design:

- **A bare `SocialMediaLink.objects` carries no tree fields.** `objects.get(pk=…).tree_path` raises `AttributeError`. The fields exist only on a `TreeQuerySet` — add them with `with_tree_fields()`, or read them off `ancestors()` / `descendants()`, which add them implicitly.
- **They are gone after `save()` / `refresh_from_db()`.** They were never on the instance; only the queryset result carried them, so a refetched instance raises the same `AttributeError`.
- **`.update()` is broken on a queryset filtered by a tree field** — `no such column: __tree.tree_path`, because the UPDATE targets the base table while the filter references the CTE alias. Use `filter(pk__in=…)` or `bulk_update`.
- **The CTE identifier `__tree` is library-internal.** `schema/resolvers.py::_in_window_subtree_roots` depends on it through `RawSQL("(__tree.tree_path[1])::bigint")`. A rename upstream surfaces as a `ProgrammingError` on the first collapsed windowed feed, not as a silently empty list.
- **Only an explicit `.order_by()` suppresses the implicit ordering — a bare `.order_by()` does not.** The compiler adds `ORDER BY tree_ordering` (depth-first) under `if not (skip_tree_fields or self.query.order_by)`, and `query.order_by` is a **tuple**: a bare `.order_by()` leaves it empty, which is falsy, so the depth-first sort of every row in the table on an un-indexable computed array is still added. `.distinct()` is a different lever and is **conditional**: `skip_tree_fields = (query.distinct and query.subquery) or <any summary annotation>`, so it suppresses the tree columns and the implicit ordering only in a **subquery** — which is exactly where the window subquery needs it, and exactly why it is also the dedup that subquery wants.
**Root Cause**: The library is not a model mixin that adds columns; it is a queryset compiler that rewrites the statement and joins a CTE named `__tree`. The ORM knows nothing about it, so every assumption the ORM makes about columns, aliases and ordering validity is false here.
**Fix**: _Use, do not fight._ The cycle guard calls `ancestors()` (which adds the fields itself) rather than reading `tree_path` off a bare manager; every structural write goes through `bulk_update`; `.distinct()` does the dedup and the ordering suppression in one call. The one place raw SQL is unavoidable is the window subquery, and it is the one expression the ORM has no equivalent for: its own `tree_path__contains` lookup is literal-only (`OuterRef("pk")` raises `TypeError`) and `RawSQL` cannot carry an `OuterRef` *parameter*, so the outer column would have to be interpolated as guessed alias text.
**Prevention**: Before reaching for `tree_path` or `tree_depth`, confirm the queryset is a `TreeQuerySet`; never hand a tree field to `.update()`, `.only()`/`.defer()` or a raw alias list; treat a `__tree`-named identifier as a versioned coupling and grep for it before bumping the library. If you need "no ordering", reach for `.distinct()` — and read the library's compiler before assuming `.order_by()` does it.

### [2026-10-01] incident: `position` is a stored sequence the library does **not** maintain — re-parenting never recomputes it

**Problem**: `OrderableTreeNode` gives `position` a column, a default of `0` and a `save()` auto-assign of `max(siblings) + 10`, and that is the whole of its maintenance. Four ways the stored number stops being a sequence:

- **Re-parenting never touches it.** A moved row keeps the number it held under its previous parent, so it lands at an arbitrary point in the new sibling set and can collide with a sibling that already holds that number. Two rows sharing a `position` makes `ORDER BY position` non-deterministic — the stored sequence is no longer a sequence.
- **The auto-assign is a non-atomic read-then-write.** Two concurrent inserts into one sibling set can read the same `max()` and write the same number.
- **`bulk_create` bypasses `save()` entirely**, so no position is assigned at all.
- **Ungrouping deliberately does not renumber.** `ungroup_social_media_links` clears `parent` only, so a promoted link keeps its old number and can tie with a root that already holds it. Every root is one sibling set with its own numbering, so the tie is legal rather than a bug — but `position` is therefore never unique and `0` is the value a row written outside `save()` carries.
**Root Cause**: The library treats `position` as an append-only hint (`max + 10`), which is enough for a tree nothing ever re-parents. Nothing expresses "this row's rank is now N", and nothing recomputes ranks on a structural change, so the invariant is entirely the caller's.
**Fix**: `services/social_link_threads.py::_reindex_siblings` renumbers the **whole** affected sibling set to `10, 20, 30, …` in the intended order on every structural write — the rows arriving first, then the stayers in `(position, pk)`, with `dropped` naming the rows that left so the vacated slot closes. Migration `0031` ranks with the same `× 10` stride, so a row the library inserts on its own lands in the same series.
**Prevention**: Treat a stored ordering column as the service's responsibility, not the model's: on any re-parent, reorder, promote or demote, compute the whole affected set's ranks deterministically and write them explicitly. Never rely on the auto-assign, and never let `bulk_create` produce rows in an ordered set.

### [2026-10-01] incident: adding a `Meta.ordering` default to an existing model changes every queryset that relied on nothing — and `position` is not grouped by parent

**Problem**: `0031` gave `SocialMediaLink` a `Meta.ordering = ["position"]` (inherited from `OrderableTreeNode.Meta`), and on a tree model that default is not inert — it is read by the library's compiler as `sibling_order = opts.ordering or opts.pk.attname`, the value used to build the computed `tree_ordering` column that orders every tree query. Three things follow, and only the first is obvious:

- **It is a behaviour change for tree queries, not just a default for unordered ones.** Before this wave the model had no `ordering`, so the sibling rank inside the depth-first `tree_ordering` was `opts.pk.attname` (`id`); after it, it is `position`. Any tree query that returned rows in a particular sibling sequence before now returns them in a different one — and a `position` collision (a promoted root, a hand-edited row, a `bulk_create` that skipped the auto-assign) makes that sequence non-deterministic, because two siblings at the same depth then produce the same `tree_ordering` string.
- **`position` is a sibling order, and nothing in the query groups by parent.** Every level of the tree numbers its children from the same base, so a child can legitimately carry the same `position` as its own parent. Sorting a flat, mixed-level queryset by it neither expresses "these two are siblings" nor clusters the list by depth. Anything that wants a sibling order must bucket on `parent_id` first — `loaders.py::_sibling_groups` does exactly that, in Python.
- **An explicit `.order_by()` on a tree queryset replaces the depth-first ordering outright** (the compiler skips adding `tree_ordering`), so an explicit ordering is a *semantic* choice on a tree query, not a cosmetic one. The two ways that goes wrong are in the sibling 2026-10-01 entry on `tree_path` being an annotation — a bare `.order_by()` does not clear it, and `.distinct()` only suppresses it in a subquery.
**Root Cause**: `Meta.ordering` reads as a declaration about the model's data ("a link has a position") rather than about a queryset's result ("these rows are in this order"). Django applies it to every unordered query, including ones whose rows are keyed by something else, and this library additionally consumes it as a *ranking input* for a computed column — so changing it reaches further than the author expects. The second trap is the natural consequence of a column whose scope is the parent, not the table.
**Fix**: _Audited, not fixed by construction._ Every `SocialMediaLink` queryset was reviewed in this wave, and the ones whose order is *not* the sibling order now say so explicitly: `line_status.py::_links_by_id` and `seed_demo_data` call `.order_by()` to clear the default, as does `loaders.py::batch_load_sublink_subtrees` (which sorts per sibling set in Python, because the order "cannot be expressed in SQL for a multi-level fetch"). The feed turned out to be unaffected because every surface already ordered explicitly (`-occurred_at, -id`).
**Prevention**: When adding or changing a `Meta.ordering` default — on any model, and especially a tree node — grep every queryset on the model and decide each one deliberately; the audit *is* the deliverable, and "nothing obviously broke" is not evidence. Ask what else reads `Meta.ordering` (here: a query compiler). When a new ordering column is scoped to a parent (or any subset), say so on the field and on every GraphQL field exposing it, and never use it as a global sort key.

### [2026-10-01] incident: `tree_filter` / `tree_exclude` on the window subquery is not a performance tweak — it silently changes the answer

**Problem**: `tree_queries`' documented performance lever restricts the base table *before* the recursion. That is harmless for "give me this node's descendants" and wrong for anything that reasons about a *whole* tree. Applied to the rank table in `schema/resolvers.py::_in_window_subtree_roots` — which maps each in-window link to its conversation's root via `tree_path[1]` — it does this: filtering down to the in-window rows deletes an out-of-window **root** from the CTE, the recursion can no longer reach anything below it, and each orphaned descendant becomes the root of its own truncated tree. `tree_path[1]` then returns the descendant rather than the conversation's real root, and the `collapseThreads` window silently stops widening to the subtree. No error and no empty list, just conversations that vanish from a day-grouped feed. It also forfeits the cheap query shape, since any tree filter forces the `__rank_table` variant with a `ROW_NUMBER()` window over the whole table.
**Root Cause**: A base-table filter changes the *tree*, not just the row set. The recursion's anchor is `parent_id IS NULL`, so removing any node removes everything it was the only path to.
**Fix**: _Avoided by construction — the optimisation was never applied._ `schema/resolvers.py::_in_window_subtree_roots` returns the unfiltered `__tree` subquery, and the reasons are written into its own docstring: the widening must reach out-of-window nodes (`_event_window` still ORs the plain `occurred_at >= bound` in, so the subquery is *additive*), moderation is root-only and would otherwise be smuggled back in through the widening, and the filter forfeits the cheap `__tree`-only template for the `__rank_table` variant. So there is no half-applied state to revert: the trap is recorded against code that deliberately does not do the thing.
**Prevention**: Before applying `tree_filter`/`tree_exclude`, state whether the query's answer depends on reaching nodes the filter removes. If it does, the filter is a semantics change — leave the subquery unfiltered and put the predicate on the outer query, which is the one that actually returns rows. The window subquery is unfiltered by design (no status, no moderation excludes, no `incident_id`) and that is load-bearing, not an oversight. Verified against a 3-level tree whose root and child are both out of window: the unfiltered subquery admits the root, the `tree_filter`-ed one does not.

### [2026-10-01] incident: the library's tree FK is hardcoded `on_delete=CASCADE` — overriding it to `SET_NULL` works only because the tree is found by field **name**

**Problem**: `tree_queries` declares the parent FK on its abstract base with `on_delete=models.CASCADE` hardcoded, and `SocialMediaLink` needs the opposite: deleting a link must **promote** its sublinks to roots rather than cascade-delete a group nobody asked to delete. The override is not only legal but not obviously safe, so it is worth recording why it works. The library locates the tree by the field **name** `parent` and its CTE hardcodes the column name — the compiler's parameter dict literally reads `"parent": "parent_id",  # XXX Hardcoded.` — which Django derives from that name; it never inspects `on_delete`. The two knobs are therefore not symmetric — **changing only `on_delete` is safe, renaming the field breaks the tree** — and the failure would be a `ProgrammingError` (or a quietly empty tree), not a validation error, because nothing checks the name at import time.
**Root Cause**: An abstract-base FK's `on_delete` is a per-model *policy* decision that gets declared once on the base, and the tree's correctness rests on a naming convention the library does not state as a requirement.
**Fix**: _Applied in the model; the library's hardcoding is untouched and still live._ `SocialMediaLink.parent` is declared explicitly on the concrete model as `TreeNodeForeignKey("self", null=True, blank=True, default=None, on_delete=SET_NULL, related_name="children")` (`incident/models.py`), so the inherited `CASCADE` is overridden without editing the abstract base. This is a *safe* override rather than a correct-by-luck one, and it is pinned rather than assumed: `tests/incident/test_social_link_tree_model.py::TreeDeletePromotionTests` asserts the subtree survives deletion **and** stays reachable from its new root — the property `SET_NULL` is actually bought for, and the one a `ProgrammingError` in the renamed CTE would break. What is *not* fixed is the coupling itself: the compiler still hardcodes `"parent": "parent_id"`, so this is a decision recorded, not a hazard removed.
**Prevention**: Overriding a third-party abstract FK's `on_delete` is fine, but grep the library for the field name before renaming it. Pin any non-default `on_delete` with a test — `tests/incident/test_social_link_tree_model.py::TreeDeletePromotionTests` asserts the subtree survives *and* stays reachable from its new root, which is the property `SET_NULL` is actually being bought for.

### [2026-10-01] common: `test_get_user_data_query_profile_aggregates` fails on the 1st of every month

**Problem**: `common/tests.py::CommonGraphQLTests.test_get_user_data_query_profile_aggregates` creates six `Event`s — four with `spotting_date = date.today()` and two with `date.today() - 1 day` — then asserts that the `MONTH`-grouped `spottingTrends` bucket for **the current month** holds all six (`assertEqual(matching_month["count"], 6)`). On the 1st of a month the two "yesterday" events belong to the *previous* month's bucket, so the current bucket holds four and the assertion fails with `4 != 6`. Confirmed on 2026-10-01: `manage.py test --keepdb` → `Ran 494 tests … FAILED (failures=1)`, and this was the suite's only failure. It is a **test** defect, not a resolver defect — `spotting_trends` groups by `spotting_date` and `get_default_start_time(MONTH)` reaches ~50 months back, so nothing is being truncated. The `aupdate(created=yesterday_dt)` two lines earlier is irrelevant to this query and is itself a leftover: grouping is on `spotting_date`, not `created`.
**Root Cause**: The fixture picks its second event date with a relative offset and then asserts against an absolute calendar bucket. "Yesterday" and "this month" coincide from the 2nd onwards, so the suite is green for 30 days and then red for one — which reads as a date-rollover flake rather than as a broken assumption.
**Fix**: _Not fixed — open, and the suite is red today._ `common/tests.py::CommonGraphQLTests.test_get_user_data_query_profile_aggregates` is untouched: it still builds two of its six events at `spotting_date=today - timedelta(days=1)` and still asserts `assertEqual(matching_month["count"], 6)` against a bucket keyed `f"{today.year:04}-{today.month:02}"`. On 2026-10-01 the full suite is `Ran 494 tests … FAILED (failures=1)` on exactly this assertion, and it is the suite's only failure — so a red `manage.py test --keepdb` today is expected, not a regression to chase. The repair is a one-line date change in the fixture (a fixed literal, or deriving the expected bucket from the same fixed date) plus dropping the `aupdate(created=yesterday_dt)` on line 380, which this query never reads; it is deferred, not blocked, and no other wave's work depends on it.
**Prevention**: Never mix a relative fixture date with an absolute calendar assertion; pick the second event's date from a fixed literal (or derive the expected bucket from that same fixed date) so the test says what it means on every day of the month. When triaging a suite failure, check whether the test's own date arithmetic assumed "not the 1st" before suspecting the code under test.

### [2026-09-30] incident: `SocialMediaLinkInput` is replace-not-patch — `occurredAt: null` is destructive

**Problem**: `update_social_media_link` treats the input as a **full replacement**: `link.url = write.url`, `link.title = write.title or ""`, and four unconditional `.set()` calls (`categories`, `lines`, `vehicles`, `stations`). Only `description`, `status`, `incident_id` and `occurred_at` are conditional, so a partial payload silently blanks the title and strips all four tag sets. `occurred_at` is `NOT NULL`, and its tri-state is deliberately asymmetric: omitted = unchanged, a value = set, explicit `null` = **reset to `link.created`** — so the usual `?? null` serialisation of an optional field is a destructive write, not a no-op, and moves the row to a different calendar day in every feed ordering built on `occurred_at`.
**Root Cause**: An input that doubles as a patch payload invites partial construction sites; "absent" had no safe meaning before the tri-state, and `null` (previously only "clear this optional field") had to be redefined for a `NOT NULL` column.
**Fix**: _Documented, not structurally enforced._ The contract is written into the field comment on `SocialMediaLinkInput.occurred_at` (`incident/schema/inputs.py`) and the service's branch comments, and pinned by `tests/incident/test_social_link_occurred_at_write.py` (`UpdateOccurredAtTests`, `OccurredAtMutationTriStateTests`). The GraphQL layer maps `Maybe` to the service sentinel by hand (`OCCURRED_AT_UNSET if not input.occurred_at else input.occurred_at.value`) because `Some.__bool__` is always `True`. Every existing construction site was audited in the same change — that audit is the actual deliverable.
**Prevention**: Adding a field to a replace-not-patch input changes **every** existing caller — grep every construction site and confirm each re-sends the field or may reset it. Treat `null` as a value with meaning: document it, and never let a `?? null` default stand in for "unchanged". The structural fix — split `updateSocialMediaLink` into a patch input — is not done; treat replace semantics as a known sharp edge.

### [2026-09-26 → 2026-09-30] incident: every stored datetime is naive **local** time (`USE_TZ = False`) — axis of two traps

**Problem**: With `USE_TZ = False` and `TIME_ZONE = "Asia/Kuala_Lumpur"`, every stored datetime is naive local wall time. Two surfaces turned that long-internal convention into an external hazard:

- **Export**: `manage.py export_official_posts` writes `posted_at` as the stored column's own `isoformat()`, so a post the X API reported as `2026-09-26T03:15:00Z` is exported as `2026-09-26T11:15:00` — a true instant with no offset, in a file whose purpose is to leave this system. The `--since`/`--until` window is unaffected (aware bounds convert into the same storage frame, so a UTC calendar day really is a UTC calendar day).
- **Migrations**: `0030`'s `occurred_at = COALESCE(posted_at, created)` must be a straight byte copy. The obvious Python loop (`link.occurred_at = link.posted_at or link.created` + `bulk_update`) round-trips every value through the field adapter and shifts the table by +08:00. The shift is invisible at the UI's minute precision and surfaces later as links ordered into the wrong calendar day against `currentServiceDayOnly` / `lastWeekOnly`.

**Root Cause**: `USE_TZ = False` makes the storage frame an application-level convention rather than a DB guarantee — nothing raises, nothing warns, and the naive value looks correct everywhere it is read. A per-row Python loop is the shape almost every Django data migration takes, and the one shape that silently re-interprets stored bytes.
**Fix**: _By design, documented._ Exported value is the stored column verbatim (spec §6.1); consumers re-anchor with `settings.TIME_ZONE`. `0030` uses `update(occurred_at=Coalesce("posted_at", "created"))` (reverse: `update(occurred_at=F("created"))`) and its docstring bans `make_aware`/`make_naive`/`astimezone`/`localtime`. Values are pinned by literal in `tests/incident/test_social_link_occurred_at_backfill.py` and `test_official_post_occurred_at.py`.
**Prevention**: Whenever a value crosses the app boundary (export, GraphQL, webhook), decide explicitly between "the stored value" and "the same instant in UTC", and pin the choice with a docstring and a test. Any migration copying a datetime between columns is a single SQL expression (`Coalesce`, `F`), never a loop. Do not "repair" a divergence between `posted_at` and `occurred_at` by converting one into the other — both come from the same `RawPost.posted_at` on the automated path, and an added `make_aware`/`astimezone` would double-shift every post. The only legitimate divergence is the `Some(None) → link.created` reset. If `USE_TZ` ever flips to `True`, re-check the export: strings gain an offset and any published dataset shifts with them.

### [2026-09-30] incident: the keyset cursor is field-agnostic — a stale token still decodes

**Problem**: `incident/schema/keyset.py` encodes a timestamp and a row id and **no column name**, so two things go wrong silently:

- **(a) A cursor minted before the column change still decodes.** A pre-`0030` token (a `created` timestamp) is still accepted by the post-`0030` resolver and silently means "resume after this `occurred_at`" — skipped or repeated rows, no error, no empty page. The same applies to `CalendarIncidentScalar.links`, and the frontend can hand a nested page-1 cursor to the root query, so one stale token crosses surfaces.
- **(b) The shared helper now serves two columns.** `SocialMediaLink` orders on `occurred_at` (both its surfaces: the root `publicSocialMediaLinks` resolver and the nested `CalendarIncidentScalar.links`); `get_line_status_reports` still orders on `LineStatusReport.created` (deliberately — a status report *is* its creation instant). The helper's name and parameters are not field-specific, so a copied resolver can silently paginate the wrong column; only the caller's variable names say which column it is.
- **(b′) Re-checked 2026-10-01, and still no move.** The link-tree wave changed `SocialMediaLink`'s `Meta.ordering`, its page composition (`collapseThreads` narrows to roots *before* the cursor) and its sort-free nested field — and deliberately left **both** sort columns alone, so the encoding stays shareable and the tree wave is not a new instance of this hazard. What the wave did add is the tempting next one: `sublinks` is a recursive nested selection with **no** `first`/`after`, so it mints no cursor at all, and its depth is bounded by the write-side `MAX_THREAD_DEPTH`. If a paginated sublink field is ever added, it is a *third* consumer and a third review of this entry.

**Root Cause**: One wire format shared by several surfaces is the right design (it is what lets the frontend hand a nested cursor to the root query), but "which column is this?" is a property of the caller, enforced only by convention. Changing a sort column additionally changes the *meaning* of an opaque token, and an opaque token cannot signal that.
**Fix**: _Not fixed — accepted, documented._ `get_public_social_media_links`'s docstring states that in-flight cursors across the deploy are not guaranteed seamless and the feed should be relaunched from page one. `keyset.py`'s module docstring names both consumers and states hazard (a) outright ("an opaque payload for one column is happily accepted by a consumer on another").
**Prevention**: (a) Changing a cursor's sort column requires either a **versioned encoding** (`"o1:"`/`"c1:"`, rejected loudly on mismatch) or **forcing clients to restart from page one**; when reviewing an `.order_by()` change on a paginated resolver, inspect every producer of that resolver's cursors. (b) When copying the helpers into a new resolver, **rename the local variables to the column you are actually ordering on** and add the resolver to the module docstring — `incident/schema/keyset.py`'s docstring already names the current two-column arrangement, so the count of consumers is checkable by reading that one file. A third column needing its own cursor is the moment to version the encoding.

### [2026-09-30] tests: `created` is `auto_now_add` — `create(created=…)` is silently ignored

**Problem**: Tests that need a `SocialMediaLink` (or any `TimeStampedModel`) at a specific `created` datetime — e.g. the `publicSocialMediaLinks` week-window and complete-day-page tests — cannot use `create(..., created=<datetime>)`: `auto_now_add` overwrites it, so every row gets "now", day-grouping assertions collapse into one day, and the test passes for the wrong reason (or fails confusingly). Same for `LineStatusReport.created`.
**Root Cause**: `TimeStampedModel.created` is `auto_now_add=True`, which Django applies at insert and which ignores any explicit value; only a subsequent `QuerySet.update()` writes the column directly.
**Fix**: Create the row first, then stamp it: `SocialMediaLink.objects.filter(pk=link.pk).update(created=<naive datetime>)` and `link.refresh_from_db()` (`PublicFeedContractTests._link`, `PublicFeedLastWeekAndDayAlignTests._link`). With `USE_TZ=False` the stamped value is naive Asia/Kuala_Lumpur local and maps straight onto the calendar day the resolver groups by.
**Prevention**: Never expect `create(created=…)` to stick on a `TimeStampedModel`; insert then `.update()`. When a pagination/grouping test asserts days, assert against distinct stamped days, not wall-clock now, so a silently-ignored stamp is caught rather than masked.

### [2026-09-12 → 2026-09-30] rosak: the test-runner ground truth (five ways the gate lies)

**Problem**: The documented test gate quietly does not do what it says:

- **`--parallel` is broken.** It crashes with `TypeError: cannot pickle 'traceback' object` as soon as any test outcome carries a traceback. The serial runner is the only reliable gate.
- **`--keepdb` loses migration-seeded rows.** `TransactionTestCase` truncates tables, including rows written by data migrations, and `--keepdb` never re-runs them — tests fail with `Clearance.DoesNotExist` and seed assertions. `get_or_create` what a test needs, or recreate the database if it degrades.
- **Concurrent runs collide.** Two `manage.py test` runs share the single `test_postgres` database and truncate/recreate each other's tables mid-run. The wreckage looks like real failures: a storm of `common_vote.content_type_id` FK violations and dozens of `DuplicateDatabase` setup errors. Run one process at a time; suspect a collision before hunting a code bug.
- **The top-level `tests/` tree is invisible.** It has no `__init__.py`, so `manage.py test tests.operation` dies in discovery (`TypeError: expected str, bytes or os.PathLike object, not NoneType`) and plain discovery skips the ~300 pytest tests entirely. pytest is not installed in the `app` container nor the host `.venv`. Module labels *do* resolve (`manage.py test tests.incident.test_social_link_threads --keepdb`) — that asymmetry is the only reason any of this is knowable.
- **The 2026-09-30 wave made it worse.** Six new modules under `tests/incident/` (**119** test functions, re-counted by AST) are invisible to the bare run. The host's system pytest 9.1.1 lacks `pytest-django`/`pytest-asyncio`, so its `pytest.ini` settings have nothing to honour them: `python3 -m pytest tests/incident --collect-only` reports 7 collected and 40 collection errors.
- **The 2026-10-01 link-tree wave made it worse again.** Three more modules (`test_social_link_tree_model` 27, `test_social_link_tree_migration` 13, `test_social_link_position_field` 16 — 56 by AST), and **192 tests green across the seven incident modules** when addressed by full dotted label. The bare `manage.py test --keepdb` run (494 tests) therefore contains **none** of that wave’s 192, and the suite's single failure that day was in `common.tests`, not in the tree work — which is exactly the shape of blind spot described here: a red bare gate is evidence about `common`, and silence is evidence about nothing in `tests/`.

**Root Cause**: The `tests/` directory is a namespace package, so Django's label discovery cannot resolve it and plain discovery skips it; nothing enforces that a suite joins a gate.
**Fix**: _Workaround._ Runnable tests live in app modules (`operation/tests.py`, `incident/tests.py`, `rosak/tests/…`) and run with app labels (`manage.py test operation incident rosak`). `tests/` tests need pytest installed or an `__init__.py` conversion before they join the gate.
**Prevention**: **A new backend test nobody's gate runs is not a test.** Put it where `manage.py test` collects it (app `tests.py` / `rosak/tests/`), or — if it must live under `tests/` — run it by its **full dotted module label** in the same change and say so in the progress entry. Never report "N tests added" without the command that executes them, and never quote a passing pytest suite as verification when the environment cannot run it. Keep the serial gate until the parallel runner is fixed.

### [2026-09-28] incident: the official-post poll's opt-in is read twice with different lifetimes — only `celerybeat` dispatch sees it

**Problem**: `OFFICIAL_POST_POLLING_ENABLED` (default off) is read in two places with different lifetimes: `rosak/celery.py` builds `beat_schedule` **at import**, so toggling the env var and restarting only `celeryworker` changes nothing — the 5-minute `ingest_official_posts` tick keeps running (or never starts) until `celerybeat` is restarted. Meanwhile `incident/tasks.py` re-reads the setting every run, so a manually-enqueued run and a beat-dispatched run can disagree with the value the operator just toggled.
**Root Cause**: The schedule is a module-level dict evaluated once at import; the task guard is a per-run read. The two layers are deliberately independent (dispatch gate + execution gate), which makes "did my env change apply?" ambiguous if only one service is restarted.
**Fix**: _By design, documented._ The settings comment and the `docs/APPS.md` beat table both state that toggling requires restarting `celerybeat`. Verify with `docker compose exec app python -c "from rosak.celery import beat_schedule; print('ingest_official_posts' in beat_schedule)"` after the restart.
**Prevention**: Every new env-gated beat entry must state the restart requirement in its settings comment and the APPS.md beat table; never verify a schedule toggle by looking at the worker alone.

### [2026-09-28] tests: the debug toolbar breaks every `self.client` request, and the cache is Redis

**Problem**: All 30 `XWebhook*` tests errored with `NoReverseMatch: 'djdt' is not a registered namespace`, and handle-resolution tests failed like a logic bug (a cache hit from a previous run changed the answer). Two environment traps that contradict the docs.
**Root Cause**: (1) `DEBUG_TOOLBAR_CONFIG["SHOW_TOOLBAR_CALLBACK"]` closes over the **module global** `DEBUG` (true in dev), but the test runner sets `settings.DEBUG = False` — `rosak/urls.py` withholds the `djdt` routes while the middleware (gated on `SENTRY_DSN`, not `DEBUG`) still renders and `_postprocess` reverses `djdt:render_panel` unconditionally. (2) `CACHES["default"]` is `RedisCache`, **not** `DummyCache` — the documented swap only applies when `DEBUG` is true, and this environment is the opposite; user-id caches use `timeout=None`, so keys survive across runs and test classes.
**Fix**: Client-based test classes carry `@modify_settings(MIDDLEWARE={"remove": ["strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"]})` (the `no_debug_toolbar` alias used by `operation/tests.py`, `rosak/tests/test_version.py`); cache-sensitive classes pin `CACHES` to a private `LocMemCache` and use a distinct user id per test.
**Prevention**: Any new test class using `self.client` needs `no_debug_toolbar`; any test whose assertions depend on a cache *hit* must pin `CACHES` to `LocMemCache` with its own `LOCATION` and must not reuse a cached key across tests. Do not trust the `DummyCache` note for this environment — check `settings.CACHES` first. A module-level `from … import _resolve_user_id` also defeats `mock.patch.object` on the source module; import it inside the function that uses it.

### [2026-09-26] incident/telegram_provider: an outbound audit row with no `payload["message"]` is silently un-approvable

**Problem**: `handlers.approve` resolves a replied-to message by JSONB lookup on `telegram_log__payload__message__message_id` + `__chat__id`. That block is written by `views.TelegramInbound` for **inbound** rows, so an admin replying `/approve` to an official-post notification got the generic "No media awaiting review found for this message." — indistinguishable from replying to an ordinary chat message, with no error and no hint the notification was real.
**Root Cause**: `TelegramLogs.payload` is a free-form `JSONField` with no constraint, and `send_message` created its OUTBOUND row *before* the send, so the row had no `message` block at all. Nothing asserted that an outbound row is reply-resolvable.
**Fix**: `send_message` gained keyword-only `return_log=False`; when set it stamps `payload["message"]` (`message_id` + `chat.id`, mirroring the inbound shape) before `asave()` and returns `(message, log)`, which `incident.tasks._notify_new_link` joins to the `SocialMediaLink` via `TelegramSocialMediaLinkLog`. The default path deliberately does **not** stamp, so existing callers are unchanged — the trap is now opt-in and silent by design. Tests: `SendMessageTests`, `ApproveHandlerTests`.
**Prevention**: Any new "reply to this message to act on it" feature must call `send_message(..., return_log=True)` and persist the returned log. If a reply handler reports "not found" for a message the bot demonstrably sent, check `TelegramLogs.payload->'message'` on that row before suspecting the handler.

### [2026-09-22 → 2026-09-26] tests: entering async code and scoping assertions

**Problem**: Three ways a test asserted nothing (or against the wrong row):

- **`asyncio.run` sees no test data.** `asyncio.run(handlers.approve(update))` inside a `TestCase` "found nothing" the test had just created: the async ORM ran on a different connection than the test transaction. `async_to_sync` made the same test pass with no other change — it runs the coroutine on the calling thread, so the wrapping transaction applies. Relatedly, a sync `Model.objects.create` inside async code raises `SynchronousOnlyOperation`; async code must use `acreate`/`asave`.
- **Patching an async symbol.** A `MagicMock` over an async function fails, because `async_to_sync` awaits the *call result* — use a real `async def`/`AsyncMock`, and patch the symbol **where it is imported** (`incident.tasks.send_message`, not `telegram_provider.utils.send_message`).
- **`Vote` assertions were unscoped.** `Vote.objects.filter(object_id=…)` can match another content type's row (object ids are unique only per content type), making `tests/incident/test_chronology_mutations.py::test_chronology_upvote_changes_downvote` order-dependent. Not fixed — scope by `content_type` (and ideally `user`); never treat `object_id` alone as identifying a vote.

**Root Cause**: Connection/transaction identity is invisible in test code, and identity is compound (`user`, `content_type`, `object_id`) where the assertion used one part.
**Fix**: Patch the admin check where it is looked up — `rosak.permissions.has_admin_claim` for function-local imports, the consumer module for module-level ones — and never let a `MagicMock` user reach it unmocked (`51f2f69`). Use `async_to_sync`, never `asyncio.run`, to enter real async code from a `TestCase`.
**Prevention**: If a query inside async code "finds nothing" that the test just created, suspect the connection, not the filter — assert against a known-id lookup before rewriting the query. Always filter `Vote` assertions by `content_type`.

### [2026-09-24] telegram_provider: `error_handler` only prints and `/dadjoke` blocks; retry is now bounded

**Problem**: `error_handler` only `print`s while `TELEGRAM_ADMIN_CHAT_ID` is unused, and `/dadjoke` does a blocking `requests.get` inside an async handler, blocking the event loop. `utils.infinite_retry_on_error` (a `while True` loop with 10s sleeps) could pin a worker forever.
**Root Cause**: Ad-hoc resilience plus a commented-out admin alert path; retries were unbounded.
**Fix**: Retry portion fixed — `infinite_retry_on_error` no longer exists; replaced by the bounded `telegram_provider.utils.retry_on_error` (`max_retries=3`, exponential backoff), landed with the governed egress path in `0d1c3a4`. Still open: `error_handler` prints instead of paging admins, `/dadjoke` still blocks, and `AGENTS.md` still names the old function.
**Prevention**: Route all outbound messaging through the governed `send_message` path (it logs `OUTBOUND`, splits at 4096 chars, dead-letters); make third-party fetches async or `sync_to_async`; alert instead of printing on handler errors.

### [2026-09-24] compose: recreate the credential-mounting services one at a time

**Problem**: `docker compose up -d` recreating `app` + `celeryworker` + `celerybeat` together intermittently fails with `OCI runtime create failed: ... not a directory: Are you trying to mount a directory onto a file (or vice-versa)?`; the affected containers exit 127/1 and the stack comes up half-dead.
**Root Cause**: Docker Desktop's WSL2 bind-mount backend races when the same host file (`~/.firebase/rosak-...json`) is bind-mounted into several containers created in parallel.
**Fix**: Recreate sequentially: `docker compose up -d --no-deps app`, then `--no-deps celeryworker`, then `--no-deps celerybeat`, and `docker compose restart web` afterwards (nginx caches the resolved upstream IP and exits if `app` is unresolvable at startup).
**Prevention**: Avoid single-command recreation of the app family on this setup.

### [2026-09-22] rosak: nginx keeps a stale `app` upstream after a container restart — 502 from :8000

**Problem**: After `docker compose restart app` the container gets a new IP, but nginx (started earlier) keeps the old one, so `http://localhost:8000/` returns 502 while granian inside `app` is healthy.
**Root Cause**: nginx resolves the upstream hostname once at startup and caches the IP; restarting only `app` does not make nginx re-resolve it.
**Fix**: `docker compose restart web` — restart nginx so it re-resolves the `app` upstream.
**Prevention**: Restart `web` alongside `app` whenever `app`'s IP changes; don't debug the app when the failure is only visible through :8000.

### [2026-09-12] rosak: container-created migrations are root-owned and unwritable by the host user — WORKAROUND

**Problem**: `makemigrations` run inside the container creates root-owned files. `./dev_permissioner.sh`'s `chown` fails for a non-root host user (it needs sudo), and pre-commit's `end-of-file-fixer`/`ruff-format` then fail with `PermissionError`.
**Root Cause**: The container runs as root while the host user owns the checkout; there is no in-band ownership handoff.
**Fix**: _Workaround._ Chown through the container from the repo root: `docker compose exec app chown -R $(id -u):$(id -g) .`.
**Prevention**: Re-own container-generated files immediately after `makemigrations`, before running any hook or `ruff format`.

### [2026-09-15] common: S3 uploads fail on OCI Object Storage — "AWS chunked encoding not supported"

**Problem**: Every `TemporaryMedia` save (incl. Telegram image attaches via `POST /upload/`) raised `botocore.exceptions.ClientError ... PutObject: AWS chunked encoding not supported.` Uploads reached OCI but were rejected with 501.
**Root Cause**: botocore >= 1.35 defaults `request_checksum_calculation` to `when_supported`, adding a CRC32 trailer (`Transfer-Encoding: chunked` + `Content-Encoding: aws-chunked` + `X-Amz-Trailer`) that OCI's S3-compat endpoint rejects. `AWS_S3_SIGNATURE_VERSION="s3v4"` does NOT help — the default is already `s3v4`; this is a checksum-trailer issue, not a signature issue.
**Fix**: `os.environ.setdefault("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required")` in `rosak/settings.py` — `PutObject` goes out as a plain body. Verified botocore honors the env var on the django-storages client; `signature_version`/`addressing_style` unchanged.
**Prevention**: Any bump of botocore/boto3 must re-check this — newer SDKs may flip behavior again. If uploads regress with this error, re-apply `when_required`. The alternative `AWS_S3_CLIENT_CONFIG={"request_checksum_calculation": ...}` (plain dict) crashes botocore in django-storages 1.14.6 — only an env var or a `botocore.config.Config` instance works.

### [2026-08-24] common: `ImgurStorage` — write path hot on every upload + silent credential failure

**Problem**: Two coupled defects left over from the Imgur → Discord migration:

- **Hot path**: `common/tasks.py:202` creates `Media` with `file=ContentFile(temp_media.file.url, …)`, routing every upload through `ImgurStorage._save` and a live Imgur API call, despite `Media.file` being marked `# TODO: Deprecate` and Discord CDN being the real host.
- **Silent degrade**: `ImgurStorage.__init__` and the module-level `ImgurClient` swallow all exceptions and print `functionality disabled`; eight `IMGUR_*` settings default to `""` (`rosak/settings.py:357-364`), so a deployment without credentials dies with `AttributeError` inside a broad `except Exception` and only increments `fail_count` — no upload can succeed despite Discord being the host.

**Root Cause**: The migration left `Media.file` wired as write path and never removed the five call sites (`STORAGE = ImgurStorage()`, `MediaMixin.__str__`, `add_width_height_to_media_task` filter, `medias_group_by_period ~Q(file="")`, `MediaAdmin.fields`). Fail-open init plus a broad exception hides the root error.
**Fix**: _Not fixed._ Requires a re-host backfill for pre-`0013` rows (fetch `i.imgur.com/<file>` → Discord webhook → fill `file_id`/`file_name`), then drop `Media.file` and delete `imgur_field.py`, `imgur_storage.py`, `management/commands/get_imgur_token.py`. Meanwhile, make init fail loudly if `Media.file` is still required.
**Prevention**: Feature-flag the storage backend; block new `Media.file` writes behind the flag and alert on `ImgurStorage._save` calls after a cutoff. Validate required credentials at `check` time; never swallow storage init errors; replace the broad `except Exception` with typed handling plus an explicit dead-letter.

### [2026-08-24] common: `FeatureFlag` missing row silently disables uploads — and gates the GC

**Problem**: `should_upload_media()` treats a missing `FeatureFlag` row as disabled (`feat_flag is not None and feat_flag.enabled`), so a fresh env with no fixture is silently off. `cleanup_temporary_media_task` early-returns on that same flag, so disabling upload also halts 30-day `TO_DELETE` GC — the staging bucket grows unbounded.
**Root Cause**: Ambiguous "missing = off" plus coupling the upload gate to garbage collection.
**Fix**: _Not fixed._ Seed one row per `FeatureFlagType` via data migration; split the GC flag from the upload flag.
**Prevention**: Data migration creating flag rows on deploy; separate `IMAGE_UPLOAD` vs `STORAGE_GC_ENABLED` flags.

### [2026-08-24] common: `Media` scalar non-null mismatch

**Problem**: `MediaScalar`/`MediaType` declare `width: int` / `height: int` non-null while `Media.width`/`height` are `null=True, default=None` — exposing more rows raises non-null resolution errors on legacy media.
**Root Cause**: Scalar nullability was not matched to the model.
**Fix**: _Not fixed._ Make the scalar widths nullable `Optional[int]` or backfill dimensions.
**Prevention**: Contract test asserting model nullability matches Strawberry scalar nullability.

### [2026-08-24] admin: ModelAdmin configuration defects

**Problem**: Four admin defects, one theme — the admin is never smoke-tested:

- `common.TemporaryMediaAdmin.prettified_metadata` calls `self.prettify_json()` but inherits `admin.ModelAdmin`, not `generic.admin.JsonPrettifyAdminMixin` → `AttributeError` and no `return`.
- `MediaAdmin` / `TemporaryMediaAdmin` use `search_fields = ["uploader"]` (an FK, not a text field) → admin search raises `FieldError`.
- `operation.LineAdmin` assigns `list_editable` twice — the second assignment wins and drops `status` inline editing.
- `TemporaryMediaStatus.RETRY_ELAPSED` (`common/enums.py:23`) is declared but assigned nowhere, so permanently dead uploads sit in `PENDING` indistinguishable from fresh rows. Assign it at `fail_count >= 5` and persist the exception string into `metadata` (`common/tasks.py:255-264`).
- `chartography.SourceCustomLine.mapped_lines` uses an explicit `through`, so Django omits it from the admin form; `SourceCustomLineLineMapping` is unregistered and `SourceCustomLineAdmin` has no inline — the admin-editable reconciliation escape hatch is unreachable. Add a `TabularInline`.

**Root Cause**: Missing mixin, FK used as a text lookup, duplicate attribute assignment, a dead status enum never wired into the retry cutoff, an explicit through not paired with an inline.
**Fix**: _Not fixed._ Inherit `JsonPrettifyAdminMixin` and return the highlighted HTML; use `search_fields = ["uploader__nickname"]`; fix `list_editable`; wire `RETRY_ELAPSED`; add the through inline.
**Prevention**: Admin smoke test hitting every `ModelAdmin` change view; exhaustive status-transition test asserting every enum member is reachable; review `list_editable`/`search_fields` when an admin changes.

### [2026-08-24] resolvers & loaders: per-key batch state and per-node re-fetch

**Problem**: DataLoader/resolver shortcuts that silently return wrong or de-ordered data:

- `batch_load_vehicle_from_line` reads `keys[0][1]`, assuming every key in the batch shares the same `spotted_today` filter — group keys by that filter before the query.
- `batch_load_spotting_count_from_vehicle` aliases its aggregate on `key[0]` only while the key is `(vehicle_id, Q(date_filter))` — two date windows for the same vehicle in one request collide and return the same count. Alias on the full composite key.
- `batch_load_medias_from_calendar_incident` returns a `set` though the field is typed `List[MediaScalar]` — media silently de-duplicated and the through-table `timestamp` ordering discarded. Return a `list`.
- `CalendarIncidentScalar.last_updated` re-fetches its row then `.count()` + an ordered slice on `chronologies` — 3 extra queries per node, invisible to `DjangoOptimizerExtension`. Annotate with `Greatest(F("modified"), Max("chronologies__modified"))` or batch.
- `batch_load_location_event_from_event` keeps the last `LocationEvent` row silently, because `event` is a FK, not a OneToOne (see the spotting entry).

**Root Cause**: Batch keys carry filter state the SQL alias ignores; "ergonomic" `keys[0]` shortcuts; collection type chosen without the ordering contract; resolvers re-fetching per node.
**Fix**: _Not fixed._
**Prevention**: Never index `keys[0]` for per-key state; include the whole key in any SQL alias; type-check loader return shapes against the field type; load-test with `assertNumQueries` and forbid per-node re-fetch in resolvers.

### [2026-08-24] incident / operation: duplicate `Line ↔ CalendarIncident` join tables — GraphQL field permanently empty

**Problem**: `CalendarIncident.lines` (`related_name="incidents"`, migration `0013`) and `operation.Line.calendar_incidents` are two separate M2M join tables. Admin `filter_horizontal` edits the former; GraphQL `Line.calendarIncidents` reads the latter, so that field is expected to be permanently empty.
**Root Cause**: Both sides declared `ManyToManyField` to each other instead of one side using the reverse accessor; `through` was left commented on `Line`.
**Fix**: _Not fixed._ Consolidate on the `Line.incidents` reverse accessor; remove the `Line.calendar_incidents` field.
**Prevention**: Single source of truth for cross-app M2M; forbid duplicate M2M declarations across apps via a `tach` rule.

### [2026-08-24] incident: `CalendarIncidentFilter.date` bare assert + month off-by-one

**Problem**: Range width is enforced with `assert … <= timedelta(days=60)` — a 500, and stripped under `python -O`; the `month` branch does `month__lte = value.month.exact + 1`, assuming a 0-indexed JS month.
**Root Cause**: `assert` used for validation; JS month indexing leaked into Python.
**Fix**: _Not fixed._ Replace the `assert` with a `GraphQLError`/`ValidationError`; fix the arithmetic to `__month=value.month.exact`.
**Prevention**: Ban bare `assert` for request validation (repo convention); filter unit tests for the 60-day boundary and month exact.

### [2026-08-24] operation: write-API scaffolding references non-existent modules + scalar mismatches

**Problem**: Commented `operation/schema/inputs.py` does `from operation.schema.enums import AssetType`, but that module does not exist — enums live in `operation/enums.py`. `StationInput.internal_representation` is a `StationLine` field misplaced on `Station`; no `VehicleInput` exists at all. In the read schema, `VehicleType` declares `info: str` while the model field is `description`, and `Asset.stations` / `StationLine.lines` declare plural lists over singular FKs.
**Root Cause**: A refactor moved the enums but the inputs stub was not updated; `Station` vs `StationLine` confusion; copy-paste scalar naming.
**Fix**: _Not fixed._ Repoint the import to `operation.enums` or the generated enum; drop/nest `internal_representation`; add `VehicleInput`/`VehiclePartialInput`; rename the scalar fields to match the model.
**Prevention**: Keep commented scaffolding importable under `if TYPE_CHECKING`; `ruff check` still covers commented files; generate scalar names from the model.

### [2026-08-24] operation: `StationLine` has no ordinal — lexicographic ordering breaks route order

**Problem**: `StationLine.Meta.ordering = ["internal_representation"]` sorts lexicographically (`KJ10` before `KJ2`), and there is no `order` field, so `Line.station_lines` cannot render travel order for strip maps / "next stations".
**Root Cause**: Missing `OrderedModel` despite `django-ordered-model` already being a dependency for `incident`.
**Fix**: _Not fixed._ Inherit `OrderedModel` with `order_with_respect_to="line"`, data-migrate `order` from the numeric tail of `internal_representation`, switch admin to `OrderedTabularInline`.
**Prevention**: Explicit route-order field; never rely on code-string ordering for sequence.

### [2026-08-24] spotting: `LOCATION` payload invariants are unenforced; deletion policy duplicated

**Problem**:

- `spotting_event_value_relevant` governs only station columns, so `type=LOCATION` can be saved with no `PointField`; GraphQL `add_event` only creates a `LocationEvent` when `input.location != UNSET`, making the type decorative.
- `LocationEvent.event` is a `ForeignKey`, not a `OneToOne`; the loader keeps the last row silently.
- The deletion rule is expressed twice: `Event.auser_deletion()` raises, while the `deleteEvent` mutation returns `ok=False` with a subtly different 3-day window (`created__gte=now()-3d`).

**Root Cause**: The constraint models station invariants only; FK chosen without uniqueness; policy expressed as a queryset filter in two places instead of one model method.
**Fix**: _Not fixed._ Extend the `CheckConstraint` (or validate in the mutation) to require a `LocationEvent` for `type=LOCATION`; migrate to `OneToOneField` after dedup; hoist the window into `Event.is_within_edit_window()` used by both paths.
**Prevention**: DB-level invariant tests per `SpottingEventType`; `OneToOneField` for 1:1 payloads; one model method for policy.

### [2026-08-24] spotting: `eventsCount` unfiltered + `with_most_entries` IndexError

**Problem**: `spotting.schema.resolvers.get_events_count` is a bare `Event.objects.acount()` ignoring `EventFilter` — a paginated UI shows the wrong total. `UserScalar.with_most_entries` indexes `[0]` into an aggregate queryset and raises `IndexError` for a user with zero events.
**Root Cause**: The count resolver does not reuse the filter `Q`; missing empty-queryset guard.
**Fix**: _Not fixed._ Pass the filtered queryset into the count; guard `with_most_entries` with an empty check (the commented `ListConnectionWithTotalCount` is the intended fix).
**Prevention**: Always derive a count from the same filtered queryset; test the zero-event user profile.

### [2026-08-24] spotting / telegram_provider: `get_daily_updates()` ignores its `spotting_date` argument

**Problem**: `telegram_provider.utils.get_daily_updates(line_id, spotting_date)` overwrites `spotting_date` with `date.today()`, so `spotting.tasks.report_spotting_today` passes `yesterday = date.today() - 1` but the digest reports today; the 03:00 beat intent is silently ignored.
**Root Cause**: Stale overwrite left after a refactor.
**Fix**: _Not fixed._ Remove the overwrite and honor the argument; pass a timezone-aware `yesterday` explicitly.
**Prevention**: Unit test asserting the digest date equals the injected date, not `today()`.

### [2026-08-24 → 2026-09-12] common / telegram_provider: JSONB lookups must match the stored shape and be fully qualified

**Problem**: Three related ways a JSONB lookup silently matches nothing:

- **Types survive into JSONB.** `TemporaryMedia.metadata` stores Telegram `message_id`/`chat_id` as ints, so `Q(metadata__telegram_message_id=source.message_id)` only matches int-vs-int; a stringified id silently matches nothing and `approve()` reports no media awaiting review.
- **Unqualified `message_id`.** `handlers.spot` joins `telegram_log__payload__message__message_id` with no `__chat__id` filter (unlike `/delete`), so message ids — unique only per chat — can bind spotting to another chat's message. `payload` has no DB index (`Meta` absent).
- **Unstamped outbound rows.** An outbound row without `payload["message"]` is not reply-resolvable (see the 2026-09-26 trap above).

**Root Cause**: `JSONField`/`JSONB` lookups preserve the stored Python type and are not schema-checked; nothing enforces that an id lookup includes its scoping key.
**Fix**: _By design / not fixed._ Store native ints and compare with the native type; add the `payload__message__chat__id` filter, a `UniqueConstraint(spotting_event, telegram_log)` and a GIN/expression index on `payload`.
**Prevention**: Always qualify a Telegram `message_id` with `chat_id`; index JSONB lookups used in production queries; add a round-trip test asserting the stored type matches the lookup argument's type.

### [2026-08-24] telegram_provider: `/approve` admin identity needs a linked user + Firebase claim — GOTCHA

**Problem**: `approve()` resolves `common.User` by `telegram_id`, then checks `has_admin_claim`. An admin who has never run `/verify` has no `User` row and is rejected before the claim is ever consulted.
**Root Cause**: The handler reuses the same "verified Telegram user" precondition as the other commands and layers the admin claim on top.
**Fix**: _By design._ Resolve the user first, then call `has_admin_claim`; the import is function-local to avoid an app-loading cycle.
**Prevention**: Document that admin bot commands require a linked `User` (`/verify`) in addition to the Firebase admin claim.

### [2026-08-24] chartography: `SourceCustomLine` admin mapping unreachable + MTREC task incomplete

**Problem**: `SourceCustomLine.mapped_lines` uses explicit `through=SourceCustomLineLineMapping`, so Django omits it from the admin form — the admin-editable reconciliation escape hatch is unreachable (see the admin entry for the inline fix). `aggregate_line_vehicle_status_mtrec_task` accepts neither `force` nor `triggered_by_id`, and no mutation can trigger it; `force` is a dead parameter and `bulk_create(ignore_conflicts=True)` discards corrections.
**Root Cause**: Explicit through not paired with an inline; the MTREC path was not given the same kwargs as the MLPTF path.
**Fix**: _Not fixed._ Give the MTREC task `force`/`triggered_by_id` plus a sibling mutation; wire `force=True` to delete conflicting `Snapshot` rows inside `transaction.atomic()`.
**Prevention**: Admin smoke test creating a mapping via the UI; mutation parity test for both sources.

### [2026-08-24] chartography: hardcoded PK map + implicit datetime coercion + assert guard

**Problem**: MTREC `short_code_line_ids_map` hardcodes numeric `operation.Line` PKs (`KGL→[2]`, `Komuter→[13,14]`) — rots on reseeding. `Snapshot.date` (a `DateField`) is assigned a `datetime` (`now() - timedelta(...)`), relying on implicit coercion that is timezone-sensitive at day boundaries. `Snapshot.url` is never populated. The shape guard is `assert isinstance(line_ids, list)`, stripped under `python -O`.
**Root Cause**: Seed-data assumptions baked into code; strict validation left as an assert.
**Fix**: _Not fixed._ Always write `custom_line_id` and resolve via the `custom_line__mapped_lines` join seeded by a data migration; use `.date()` explicitly in the defined timezone; raise an explicit exception for an unknown short code; populate `Snapshot.url`.
**Prevention**: Forbid hardcoded PKs; validate external payload shapes with explicit errors, not `assert`.

### [2026-08-24] reporting: dormant GraphQL layer — enums, uniqueness, authz

**Problem**: The `reporting` app is parked with a broken/unfinished surface:

- `reporting/schema/filters.py` and `inputs.py` import `reporting.schema.enums`, which does not exist; `Report.type` is a plain `TextField(choices=...)`, so `strawberry.auto` renders `String`, not the `ReportType` enum.
- `ReportFilter.filter_types` filters `report_type__in` while the model field is `type`; no `UniqueConstraint` on `Vote(report, user)` (repeated `createVote` stuffs the ballot), and the same missing uniqueness on `ReportMedia`/`ReportResolution` allows duplicate attachments/links (compare `operation.AssetMedia`).
- Auto-generated `delete_reports` / `delete_vote` carry no `permission_classes`, and `VoteInput.user_id` / `ReportInput.reporter_id` are client-supplied — any caller can vote or file as any user.

**Root Cause**: The scaffolded GraphQL layer was never completed; the model used plain choices instead of `TextChoicesField`; authz was never reviewed.
**Fix**: _Not fixed._ Create a Strawberry enum over `reporting.enums.ReportType` per `generic/schema/enums.py`, switch `Report.type` to `TextChoicesField(choices_enum=…)`; fix the filter to `type__in`; add uniqueness plus an idempotent `toggle_vote` deriving `user_id` from `info.context.user.id`; derive voter/reporter server-side and gate mutations `IsLoggedIn+IsRecaptcha` with owner-delete checks.
**Prevention**: Never trust a client-supplied `user_id`; unique constraint on every vote/through table; CI import-check even for dormant apps.

### [2026-08-24] generic: `GeometricForm` dead `required` + shared-`Meta` mutation + `longitude==0` dropped

**Problem**: `GeometricForm.required` is `None` (falsy) but `latitude`/`longitude` are built in the parent class body with `required=required` while it is still `None`, so a subclass's `required=False` is never read. Subclasses configure by mutating the parent's shared `GeometricForm.Meta` (e.g. `Meta.widgets={"location": HiddenInput()}` in `incident` but commented out in `spotting`/`operation`), so whether `location` renders hidden depends on import order. `clean()` does `if latitude and longitude` — a legitimate `longitude==0` (prime meridian) is silently dropped.
**Root Cause**: Class-attribute mutation instead of per-subclass `Meta`; truthiness check instead of `is not None`.
**Fix**: _Not fixed._ Move model/widget config into per-subclass `Meta` or an `__init_subclass__` hook; build the fields in `__init__` from `self.required`; change `clean()` to `if latitude is not None and longitude is not None`.
**Prevention**: Never mutate a parent `Meta`; add a `longitude=0` test case.

### [2026-08-24] generic: `WebLocationInput` UNSET unreachable + empty schema roots + dead code

**Problem**: `WebLocationInput` fields are `Optional[float]` with no default — Strawberry renders them nullable-but-required, so the `if input.location != strawberry.UNSET` branch in `spotting/schema/schema.py:125-155` is unreachable. `GenericScalars`/`GenericMutations`/`PublicSpottingStats` are empty `@strawberry.type`s, so wiring them fails schema construction. `generic/types.py`'s `Point2D` TypedDicts are unused; `generic/schema` has no `__init__.py` (implicit namespace); `generic/tests.py` is 0 bytes — primitives used by five apps have no coverage.
**Root Cause**: Incremental scaffolding left incomplete.
**Fix**: _Not fixed._ Give each `WebLocationInput` field `= strawberry.UNSET`; add `__init__.py`; promote `Point2D_SearchField` to a real `@strawberry.input` with a shared `Q`-builder for point-radius search (needed by `operation`, `spotting`, `incident`).
**Prevention**: Test that `strawberry.UNSET` branches are reachable; require `__init__.py` for every `schema` package.

### [2026-08-24] rosak: single async GraphQL endpoint — `DEBUG=True` swaps Redis for `DummyCache` + disables the introspection guard

**Problem**: Local `DEBUG=True` replaces the Redis cache with `DummyCache` and disables introspection only when `DEBUG=False` — cache bugs are not reproducible locally. (The 2026-09-28 test-env entry shows the inverse trap: a `DEBUG=False` environment with real Redis, so **check `settings.CACHES` rather than trusting this note**.)
**Root Cause**: Dev convenience swallowing the cache layer; the introspection gate is coupled to `DEBUG`.
**Fix**: _Not fixed — by design._ Documented trap; use a `DummyCache`-aware test harness or run with `DEBUG=False` locally for cache repro.
**Prevention**: CI runs with a prod-like cache; add an integration test toggling `DEBUG`.

### [2026-08-24] rosak: `common/tasks.py` circular import hazard

**Problem**: `common/tasks.py` imports `spotting` and `incident` at module top level while both apps import `common` — a genuine cycle, and the reason most other imports in that file are function-local.
**Root Cause**: The task needs cross-app models but lives in `common`.
**Fix**: _Not fixed._ Lazify the imports or move task ownership to a leaf app; `tach.yml` already documents the allowed edges.
**Prevention**: Enforce `tach check` in CI; prefer lazy string refs and function-local imports for cross-app models.

---

## Fixed

Historical fixes with no live action; kept so the ground isn't re-covered. Full detail in git.

- **2026-09-28** — `incident`: the X webhook read `includes` from the wrong envelope level (`payload.includes` instead of `data.includes`), so every real delivery was dropped; `_expansion_containers` now checks `data` first (`3f1723f`). Build webhook fixtures from a real captured body or the vendor schema, never by hand.
- **2026-09-28** — `incident`: `html.unescape` is applied exactly once in `official_posts.tweet_to_raw_post`, so all ingest paths store decoded text while `RawPost.raw`/`raw_payload` stay encoded for export fidelity (`e099157`).
- **2026-09-26** — `incident`: auto-ingested `PENDING_APPROVAL` links no longer leak into the public feed (`exclude(is_automated=True, status=PENDING_APPROVAL)`); the exclusion stays scoped to `is_automated` so community pending rows remain visible. Approval: console queue or Telegram `/approve` (`a2f92ea`).
- **2026-09-24** — `rosak`: `has_admin_claim` catches only `auth.UserNotFoundError` and returns False; other Firebase errors still propagate (`6a8f25e`).
- **2026-09-24** — `rosak`: a `rosak/tests.py` module shadows the `rosak/tests/` package and aborts discovery; use a `test_*.py` name instead (`bc45bf1`).
- **2026-09-24** — `operation`: `LineAdmin.exclude = ("calendar_incidents",)` — the auto-rendered M2M fetched every incident and was `blank=False` (`6ab47e8`).
- **2026-09-24** — `telegram_provider`: `/spotting_today` used the spotting enum's `NOT_IN_SERVICE` on `operation.Vehicle.status`; now `VehicleStatus.OUT_OF_SERVICE` (`6075118`).
- **2026-09-24** — `tests`: patch the admin check where it is looked up (function-local import → `rosak.permissions.has_admin_claim`; module-level → the consumer module) (`51f2f69`).
- **2026-09-22** — `spotting`: Firebase credential bind-mounted from a nonexistent path → Docker created a root-owned directory; mount `${HOME}/…` and fail fast in `SpottingConfig.ready()` (`46cfde5`).
- **2026-09-22** — `compose`: `celerybeat`'s explicit `volumes:` replaces the YAML anchor's list (no deep merge for sequences); re-declare the credential mount (`2acbbc2`).
- **2026-09-22** — `incident`: `bucket_hourly` stopped at the current hour; it now returns all 24 service-day buckets, or `[]` when the line has no report in the day (`e1c64e1`).
- **2026-09-16** — `incident`: submitter link edits force `PENDING_APPROVAL` and are own-links-only, admin edits keep status, and an omitted `incident_id` preserves the association while an explicit `null` detaches it (`8bc4847`).
- **2026-09-16** — `telegram_provider`: with uploads disabled, `handlers.media` now records the `TemporaryMedia` row (`metadata["uploads_disabled"] = True`) instead of dropping it — gate publication, not ingestion (`0882c80`).
- **2026-09-13** — `incident`: migrations `0015`/`0016` backfill pre-existing rows to `LIVE`; the `DRAFT` default governs only rows created afterwards (`038d23b`).
- **2026-09-12** — `common`: video conversion branches on `metadata["mime_type"]` and skips PIL/EXIF instead of raising `UnidentifiedImageError` (`82addcc`).
- **2026-09-12** — `rosak`: regenerate `rosak/tests/snapshots/schema.graphql` whenever GraphQL fields or types change (`0ff57ec`).
- **2026-08-25** — `telegram_provider`: unbounded `infinite_retry_on_error` replaced by bounded `retry_on_error` (`max_retries=3`, exponential backoff) in the governed egress path (`0d1c3a4`); the error handler and blocking fetch remain open (see traps).
- **2026-08-24** — `common`: NSFW moderation re-enabled for non-trusted uploads, trusted clearance preserved (`1e2a421`).
- **2026-08-24** — `common`: `get_default_start_time()` uses `date.replace()` so YEAR/MONTH/WEEK no longer raise `AttributeError` (`bb1e519`).
- **2026-08-24** — `incident`: `StationIncident`'s `UniqueConstraint` gained `condition=Q(is_last=True)`, matching `VehicleIncident` (`1e2a421`).
- **2026-08-24** — `spotting`: `markAsRead` un-gated from `IsAdmin` to `IsLoggedIn` (`1e2a421`).
- **2026-08-18** — `generic`: `GeoMultiPoint` no longer reuses the `GeoLineString` GraphQL type name (`c318fd4`).

---

*Sources: `docs/APPS.md` § Known Defects & Traps; `docs/components/*.md`; git history. Entry dates are catalogue dates unless a fix commit is shown.*

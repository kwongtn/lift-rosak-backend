# MISTAKES.md — rosak_backend Known Defects & Traps

> Catalog of defects, traps and cross-component gaps so future agents don't repeat them.
> Entries use **Problem** / **Root Cause** / **Fix** / **Prevention**. Entries sharing a root cause are
> one entry with a bullet per case; a range of dates in a title is replaced by the earliest date plus a
> note of recurrences. Fully historical fixes are one-liners under `## Fixed`. Earlier detail: `git log -p -- MISTAKES.md`.
> Dates are catalogue dates unless a fix commit is shown. `docs/APPS.md` § Known Defects & Traps is the compact index of open traps.

---

## Traps

### [2026-10-21] common: `MediaType.createdDate` costs one query per photo

**Problem**: `medias(first: 100) { edges { node { id createdDate … } } }` runs 101 SQL queries; with `createdDate` removed the same page runs 1. Measured on the dev DB: about 700 ms against about 160 ms for 100 photos, 25 queries for 24 photos. `media(id)` pays one extra query for the same reason. The gallery's feed query selects `createdDate`.
**Root Cause**: `MediaType.created_date` is a plain `@strawberry_django.field` method that reads `self.created`. The optimizer's `.only(...)` only knows the model fields the selection names (`id`, `file`, `width`, `height`, `uploader`), so `created` is deferred and every node refetches it (`SELECT created, id … LIMIT 21`).
**Fix**: _Not fixed._ `@strawberry_django.field(only=["created"])` on `created_date` removes it (verified: 1 query for 100 photos). No schema change.
**Prevention**: A resolver that reads a model field must declare it with `only=` / `select_related=` / `prefetch_related=`. When adding a resolver-backed field to a connection node, read the `SQLPanel` subtitle in the local response (`debugToolbar`, `DEBUG=True`) and compare 1 node with 24.

### [2026-10-21] operation: the dev DB holds `Line.telegram_channel_id` uniqueness as a bare unique index, so name-based `DROP CONSTRAINT` fails

**Problem**: `manage.py migrate` of a plain `AlterField(unique=True -> False)` on `Line.telegram_channel_id` failed on the dev DB with `ProgrammingError: constraint "operation_line_telegram_channel_id_key" of relation "operation_line" does not exist`, while the test DB (built by migrations) applied it fine.
**Root Cause**: Schema drift. Migrations create a UNIQUE **constraint**, but the dev DB (restored from a dump) has only a unique **index** of the same name, and no `_like` index. Django's AlterField emits `ALTER TABLE ... DROP CONSTRAINT <name>`, which cannot drop a bare index. Seen only on this column (`code`/`display_name` are real constraints); production's form is unverified.
**Fix**: `operation/migrations/0018` drops the uniqueness by column through `connection.introspection.get_constraints()`: `DROP INDEX` for an index, `DROP CONSTRAINT` for a constraint, plus the `_like` index (`d0a2dd9`). Run forward, reverse and forward again on the dev DB.
**Prevention**: Before a migration that removes or renames a constraint or index, compare `pg_constraint` / `pg_indexes` on the dev DB with what migrations would build, and drop by column rather than by name when they differ.

### [2026-10-21] common: media tasks re-enqueue themselves forever (`time.sleep(2)`, no cap) when their row is missing

**Problem**: `check_temporary_media_nsfw`, `convert_temporary_media_to_media_task` and `add_width_height_to_media_task` (`common/tasks.py`) treat "row not found" as transient: `time.sleep(2)`, then `apply_async` of themselves with the same kwargs. There is no counter and no cap (`bind=True` but nothing reads `self.request.retries`). A row that never appears (deleted by the `TO_DELETE` purge in `cleanup_temporary_media_task`, a wrong id, a `filename` that never matches `Media.file`) loops forever, and each cycle blocks a worker for 2 s.
**Root Cause**: A "wait for the row" workaround written as an unbounded self-requeue instead of a bounded Celery retry.
**Fix**: _Not fixed._ Replace the sleep-and-requeue with `self.retry(countdown=2, max_retries=N)` (or `apply_async(countdown=2)` with a carried attempt counter) and log or dead-letter at the cap.
**Prevention**: Every task that re-enqueues itself needs an attempt cap and must never `sleep` inside a worker (repo rule: Celery retries are bounded).

### [2026-10-21] common: the NSFW verdict cannot reliably gate publishing — convert and the NSFW check race

**Problem**: `common/signals.py::convert_temporary_media_to_media` dispatches `convert_temporary_media_to_media_task` **and** `check_temporary_media_nsfw` together for every `PENDING` upload from a non-trusted uploader. Convert refuses only `BLOCKED` / `TO_DELETE` / `INVALID_UPLOAD`, so it processes a `PENDING` row without waiting for a verdict and ends by setting `TO_DELETE`; the NSFW task then returns at `status is not PENDING` and never scores the image. Which task wins decides whether `BLOCKED` stops publication. The NSFW task's `CLEARED` branch dispatches convert again, and `cleanup_temporary_media_task` re-drives `PENDING` rows older than 5 minutes into convert regardless of any verdict. Videos skip the NSFW check by design.
**Root Cause**: Moderation sits beside conversion instead of in front of it: `PENDING` is both the state the NSFW task needs to see and a state convert accepts, and no code orders the two tasks.
**Fix**: _Not fixed._ Order them explicitly: NSFW first, convert only from `CLEARED` / `TRUSTED_CLEARED` (videos exempt on purpose), and revisit the cleanup task's `PENDING` re-drive.
**Prevention**: A moderation gate must be the only path to publish. Test that a `BLOCKED` verdict (and a missing verdict for a non-trusted image) leaves no `Media` row.

### [2026-10-20] operation: date-only `lastSpottingDate` cannot order same-day sightings

**Problem**: "Most Recently Spotted" on the line overview showed vehicle 110 (MRT Kajang Line) although 151 was spotted later. Seven vehicles tied on `lastSpottingDate` 2026-10-18 and the frontend picked by list order (its comparator never returned `0` on ties).
**Root Cause**: `Event.spotting_date` is a `DateField`, so `Vehicle.last_spotting_date` has no time of day and cannot separate same-day sightings.
**Fix**: `eff71aa` added `Vehicle.lastSpottedAt: DateTime` (`scalars.py::last_spotted_at` → `last_spotted_at_from_vehicle_loader` → `batch_load_last_spotted_at_from_vehicle_id`). One `DISTINCT ON` query returns the `created` of each vehicle's event with the highest `(spotting_date, created)`, excluding the same statuses as `lastSpottingDate`. The frontend sorts by `lastSpottingDate`, then `lastSpottedAt`. Pinned by `tests/operation/test_last_spotted_at_loader.py`.
**Prevention**: Never order by a date-only column when rows can share a day; add a timestamp tiebreaker and test with several rows on one day.

### [2026-10-19] tests: async pytest tests under `tests/` commit rows outside the test transaction — a kept test DB then breaks `manage.py test --keepdb`

**Problem**: After a pytest run that includes the async tests under `tests/`, `manage.py test --keepdb` reports about **47 errors** against the kept test database.
**Root Cause**: The async pytest tests commit rows outside the per-test transaction, so the kept DB carries that data into the Django runner.
**Fix**: _Workaround._ After any pytest run, run `docker compose exec app python manage.py test` **without** `--keepdb` to rebuild the test DB (noted in `AGENTS.md`).
**Prevention**: Never run pytest and `--keepdb` against the same test DB back to back. If the Django run suddenly shows dozens of errors after a pytest run, suspect the kept DB before the code.

### [2026-10-19] incident: `DjangoOptimizerExtension` cannot see objects a DataLoader returns — pulse-link N+1 on the front-page `lines` query

**Problem**: The front-page `lines` query resolved each line's pulse links through a loader, and every link lazy-loaded its `user` and `lines`, one query per link.
**Root Cause**: `DjangoOptimizerExtension` optimizes only the queryset Strawberry-Django builds for the field it resolves. Rows a DataLoader returns come from a plain queryset it never inspects, so their relations are not prefetched.
**Fix**: `25eda73`: `incident/services/line_status.py::_links_by_id` uses `select_related("user").prefetch_related("lines")`. Pinned by `tests/incident/test_line_status_loader.py::test_pulse_links_query_count_does_not_scale_with_link_count`.
**Prevention**: A loader that returns model instances must apply its own `select_related` / `prefetch_related` for every field its GraphQL type resolves. Pin it with a `CaptureQueriesContext` count test.

### [2026-10-01] incident: `tree_queries` puts its loop protection in `clean()`, so a plain `save()` writes a **silent cycle no tree query can reach**

**Problem**: `django-tree-queries` rejects a cycle only in `TreeNode.clean()`, which only `full_clean()` runs, so `link.parent = other; link.save()` writes a cycle with no error. The recursive CTE anchors on `parent_id IS NULL`, so a node inside a cycle is unreachable from **every** tree query (`descendants()`, `ancestors()`, the loader's subtree fetch return nothing), and `ancestors()` *on* the cycled node raises `DoesNotExist` (a 500, not `[]`). There is no API repair path, only a hand-written `UPDATE`.
**Root Cause**: A cross-row invariant cannot be a row `CHECK`; the library put it in the framework hook Django treats as opt-in, so it is only as strong as caller discipline, and no default caller has it.
**Fix**: `SocialMediaLink.save()` runs `_guard_tree_cycle` **before** `super().save()` and raises `django.core.exceptions.ValidationError` (the type `TreeNode.clean()` raises; not `IncidentServiceError`, which a model cannot import without a cycle; not `assert`, stripped under `python -O`). A self-parent is caught up front because the ancestor walk cannot see it. `full_clean()` is not called: it would revalidate every field on every save. The check is skipped when `update_fields` omits `parent`, and **both** spellings count: Django accepts a field's `name` or `attname` (`Model._save_table` keeps a field on `f.name in update_fields or f.attname in update_fields`), so `save(update_fields=["parent_id"])` writes the `parent` column. Matching `"parent"` alone was a live hole, verified by intercepting `Model._do_update` (the UPDATE carried `['modified', 'parent']`, no error). `telegram_provider.handlers`'s `save(update_fields=["status"])` still skips the two-query walk. `bulk_create`/`bulk_update` bypass `save()`, so `services/social_link_threads.py::_assert_no_cycle` re-checks before any write. Pinned by `tests/incident/test_social_link_tree_model.py::TreeCycleGuardTests`.
**Prevention**: Enforce a cross-row invariant on a self-FK model in `save()`, not `clean()`; read whether a library's loop protection lives in `clean()`, a constraint, or nowhere. Scope a two-query guard to the field that can violate it, and when the scope is a string match on `update_fields`, match every accepted spelling (name and attname).

### [2026-10-01] incident: `tree_path` is a recursive-CTE **annotation**, not a column — five ORM idioms that are correct elsewhere break on it

**Problem**: `django-tree-queries` stores nothing: `tree_path` / `tree_depth` / `tree_ordering` are computed per query by a CTE the library prepends. Consequences:

- **A bare `SocialMediaLink.objects` has no tree fields.** `objects.get(pk=…).tree_path` raises `AttributeError`; add them with `with_tree_fields()` or read them off `ancestors()` / `descendants()`, which add them implicitly.
- **They are gone after `save()` / `refresh_from_db()`**; only the queryset result carried them.
- **`.update()` on a queryset filtered by a tree field breaks** with `no such column: __tree.tree_path` (UPDATE targets the base table, the filter references the CTE alias). Use `filter(pk__in=…)` or `bulk_update`.
- **The CTE identifier `__tree` is library-internal.** `schema/resolvers.py::_in_window_subtree_roots` depends on it via `RawSQL("(__tree.tree_path[1])::bigint")`; an upstream rename surfaces as a `ProgrammingError` on the first collapsed windowed feed, not as an empty list.
- **Only an explicit `.order_by(…)` suppresses the implicit ordering; a bare `.order_by()` does not.** The compiler adds `ORDER BY tree_ordering` under `if not (skip_tree_fields or self.query.order_by)` and `query.order_by` is a tuple, so a bare `.order_by()` leaves it empty (falsy) and the depth-first sort of the whole table on an un-indexable computed array is still added. `.distinct()` is conditional: `skip_tree_fields = (query.distinct and query.subquery) or <any summary annotation>`, so it suppresses tree columns and ordering only in a **subquery**, which is exactly where the window subquery needs it (and why it is also the dedup that subquery wants). An explicit `.order_by(…)` on a tree queryset replaces the depth-first order outright, so it is a semantic choice, not cosmetic.

**Root Cause**: The library is a queryset compiler that rewrites the statement and joins a CTE named `__tree`, not a model mixin that adds columns, so every ORM assumption about columns, aliases and ordering is false here.
**Fix**: _Use, do not fight._ The cycle guard calls `ancestors()` rather than reading `tree_path` off a bare manager; structural writes go through `bulk_update`; `.distinct()` does dedup and ordering suppression in one call. Raw SQL is unavoidable only in the window subquery: the library's `tree_path__contains` lookup is literal-only (`OuterRef("pk")` raises `TypeError`) and `RawSQL` cannot carry an `OuterRef` parameter.
**Prevention**: Confirm the queryset is a `TreeQuerySet` before touching `tree_path`/`tree_depth`; never hand a tree field to `.update()`, `.only()`/`.defer()` or a raw alias list; grep for `__tree` before bumping the library. For "no ordering" use `.distinct()` (in a subquery) and read the compiler before assuming `.order_by()` does it.

### [2026-10-01] incident: `position` is a stored sequence the library does **not** maintain — re-parenting never recomputes it

**Problem**: `OrderableTreeNode` gives `position` a column, default `0` and a `save()` auto-assign of `max(siblings) + 10`, and nothing more. The stored number stops being a sequence when:

- **A row is re-parented.** It keeps its old number, lands arbitrarily in the new sibling set and can tie with a sibling, making `ORDER BY position` non-deterministic.
- **Two inserts race.** The auto-assign is a non-atomic read-then-write; concurrent inserts can read the same `max()`.
- **`bulk_create` is used.** It bypasses `save()`, so no position is assigned (`0`).
- **A link is ungrouped.** `ungroup_social_media_links` clears `parent` only, so a promoted link keeps its number and can tie with a root. Every root is one sibling set with its own numbering, so the tie is legal, but `position` is never unique.

**Root Cause**: The library treats `position` as an append-only hint, enough for a tree nothing re-parents. Nothing recomputes ranks on a structural change, so the invariant is entirely the caller's.
**Fix**: `services/social_link_threads.py::_reindex_siblings` renumbers the **whole** affected sibling set to `10, 20, 30, …` on every structural write: arriving rows first, then stayers in `(position, pk)`, with `dropped` naming rows that left so the vacated slot closes. Migration `0031` ranks with the same `× 10` stride.
**Prevention**: Treat a stored ordering column as the service's job: on any re-parent, reorder, promote or demote, compute the whole affected set's ranks and write them explicitly. Never rely on the auto-assign or let `bulk_create` produce rows in an ordered set.

### [2026-10-01] incident: adding a `Meta.ordering` default to an existing model changes every queryset that relied on nothing — and `position` is not grouped by parent

**Problem**: `0031` gave `SocialMediaLink` `Meta.ordering = ["position"]` (inherited from `OrderableTreeNode.Meta`). On a tree model that is not inert: the library's compiler reads `sibling_order = opts.ordering or opts.pk.attname` to build the computed `tree_ordering` column behind every tree query.

- **Tree queries change behaviour.** Sibling rank inside the depth-first `tree_ordering` went from `id` to `position`, so tree queries return a different sibling sequence, and a `position` collision makes it non-deterministic (two siblings at one depth yield the same `tree_ordering` string).
- **`position` is a sibling order and nothing groups by parent.** Every level numbers its children from the same base, so a child can carry its parent's `position`. Sorting a flat mixed-level queryset by it neither expresses siblinghood nor clusters by depth. Bucket on `parent_id` first, as `loaders.py::_sibling_groups` does in Python.
- **An explicit `.order_by()` replaces the depth-first order** (see the `tree_path` entry above).

**Root Cause**: `Meta.ordering` reads as a declaration about data ("a link has a position") but Django applies it to every unordered query, and this library also consumes it as a ranking input, so a change reaches further than expected. The second trap follows from a column scoped to the parent, not the table.
**Fix**: _Audited, not fixed by construction._ Every `SocialMediaLink` queryset was reviewed; those whose order is not the sibling order now say so: `line_status.py::_links_by_id` and `seed_demo_data` call `.order_by()` to clear the default, as does `loaders.py::batch_load_sublink_subtrees` (sorts per sibling set in Python; the order "cannot be expressed in SQL for a multi-level fetch"). The feed was unaffected because every surface already orders explicitly (`-occurred_at, -id`).
**Prevention**: When adding or changing a `Meta.ordering` default, grep every queryset on the model and decide each deliberately; the audit is the deliverable ("nothing obviously broke" is not evidence). Ask what else reads `Meta.ordering` (here a query compiler). Say on the field and every GraphQL field exposing it that a parent-scoped column is never a global sort key.

### [2026-10-01] incident: `tree_filter` / `tree_exclude` on the window subquery is not a performance tweak — it silently changes the answer

**Problem**: The library's documented lever restricts the base table *before* the recursion. That is harmless for "descendants of this node" and wrong for anything about a *whole* tree. Applied to the rank table in `schema/resolvers.py::_in_window_subtree_roots` (maps each in-window link to its conversation root via `tree_path[1]`), filtering to in-window rows deletes an out-of-window **root** from the CTE, the recursion cannot reach anything below it, and each orphaned descendant becomes the root of its own truncated tree. `tree_path[1]` then returns the descendant, and the `collapseThreads` window silently stops widening to the subtree: no error, no empty list, just conversations vanishing from a day-grouped feed. Any tree filter also forces the `__rank_table` variant (a `ROW_NUMBER()` window over the whole table) instead of the cheap `__tree`-only template.
**Root Cause**: A base-table filter changes the *tree*, not just the row set. The anchor is `parent_id IS NULL`, so removing a node removes everything it was the only path to.
**Fix**: _Avoided by construction._ `_in_window_subtree_roots` returns the unfiltered `__tree` subquery (reasons in its docstring): the widening must reach out-of-window nodes (`_event_window` still ORs in the plain `occurred_at >= bound`, so the subquery is additive), and moderation is root-only and would be smuggled back in through the widening.
**Prevention**: Before applying `tree_filter`/`tree_exclude`, state whether the answer depends on nodes the filter removes; if so, leave the subquery unfiltered and put the predicate on the outer query. The window subquery is unfiltered by design (no status, moderation or `incident_id` filter) and that is load-bearing. Verified on a 3-level tree whose root and child are both out of window: the unfiltered subquery admits the root, the filtered one does not.

### [2026-10-01] incident: the library's tree FK is hardcoded `on_delete=CASCADE` — overriding it to `SET_NULL` works only because the tree is found by field **name**

**Problem**: `tree_queries` declares the parent FK on its abstract base with `on_delete=models.CASCADE`; `SocialMediaLink` needs deletion to **promote** sublinks to roots instead. The override is safe but not obviously so: the library locates the tree by the field **name** `parent` and its CTE hardcodes the column (`"parent": "parent_id",  # XXX Hardcoded.`), never inspecting `on_delete`. Changing only `on_delete` is safe; **renaming the field breaks the tree** with a `ProgrammingError` or a quietly empty tree, because nothing checks the name at import.
**Root Cause**: `on_delete` is a per-model policy declared once on the base, and the tree's correctness rests on a naming convention the library does not state as a requirement.
**Fix**: `SocialMediaLink.parent` is declared on the concrete model as `TreeNodeForeignKey("self", null=True, blank=True, default=None, on_delete=SET_NULL, related_name="children")` (`incident/models.py`); the hardcoding is untouched, so the coupling is recorded, not removed. Pinned by `tests/incident/test_social_link_tree_model.py::TreeDeletePromotionTests` (the subtree survives deletion **and** stays reachable from its new root).
**Prevention**: Overriding a third-party abstract FK's `on_delete` is fine; grep the library for the field name before renaming it, and pin any non-default `on_delete` with a test.

### [2026-10-01] tests: fixtures built as offsets from "now" or a rollover helper flip at calendar / service-day boundaries

**Problem**: Two tests passed all day except at one boundary.

- `common/tests.py::CommonGraphQLTests.test_get_user_data_query_profile_aggregates` made two of six events `today - 1 day` and asserted the current month's `MONTH` `spottingTrends` bucket held six. On the 1st, yesterday is last month, so it failed with `4 != 6` (`Ran 494 tests … FAILED (failures=1)`, the suite's only failure on 2026-10-01). The neighbouring `aupdate(created=yesterday_dt)` was irrelevant: grouping is on `spotting_date`.
- Two fixtures in `tests/incident/test_social_link_feed_ordering.py` used `boundary = service_day_start(timezone.now())` and `root = boundary + timedelta(hours=2)`. `service_day_start` is the service day at `DAY_START_HOUR = 3` and **before 03:00 resolves to the PREVIOUS day's 03:00** (`if now < candidate: candidate -= timedelta(days=1)`), so between 00:00 and 03:00 "today 05:00" was yesterday 05:00, a root believed inside the window sat on its lower bound, and `assertEqual(self._ids(self._feed(lastWeekOnly=True, collapseThreads=True)), [])` returned `[root.id]` (pre-fix at 00:05: `AssertionError: Lists differ: ['16784'] != []`). The sibling fixture `test_both_window_flags_together_carry_one_recursive_cte_each` had the same latent failure behind a reassuring comment.

**Root Cause**: A relative fixture instant asserted against an absolute calendar bucket, or an offset from a helper with a discontinuity: `service_day_start` is hour-derived and moves back at 03:00, whereas `last_week_start` is date-derived and stable, so `last_week_start + N days` is safe. `USE_TZ = False` hides it: boundary, fixture and resolver read the same naive local clock, so nothing raises.
**Fix**: `73142d4` made the month test's second day month-relative (yesterday, or today on the 1st) and the `withMostEntries(DAY)` expectation follows it. `ba4447d` re-anchored the feed fixtures to absolute wall time: `today_midnight = datetime.combine(timezone.now().date(), time.min)` plus fixed offsets (`root = today_midnight + timedelta(hours=2)`, `child = today_midnight - timedelta(days=10)`, `grandchild = today_midnight - timedelta(days=11)`; CTE-count test: `root = today_midnight - timedelta(days=7)`, `child = today_midnight + timedelta(hours=3)`, outside both windows' bounds at every hour). Assertions kept; comments now true at any hour.
**Prevention**: Anchor fixture dates to the bucket they feed (calendar midnight plus a fixed offset), not "now ± n days" or a rollover helper (those are the resolver's bounds; use them only in a test about the boundary). A fixture that must sit inside a window must hold at both ends of the discontinuity, and its comment should say which instant it is. Audit a suspect fixture by re-running the module with `django.utils.timezone.now` frozen at several hours (00:05, 02:59, 03:00, 03:05, 23:55), which is valid only for fixtures that set `created` explicitly (see the `created` entry below).

### [2026-09-30] incident: `SocialMediaLinkInput` is replace-not-patch — `occurredAt: null` is destructive

**Problem**: `update_social_media_link` treats the input as a **full replacement**: `link.url = write.url`, `link.title = write.title or ""`, and four unconditional `.set()` calls (`categories`, `lines`, `vehicles`, `stations`). Only `description`, `status`, `incident_id` and `occurred_at` are conditional, so a partial payload blanks the title and strips all four tag sets. `occurred_at` is `NOT NULL` with a deliberately asymmetric tri-state: omitted = unchanged, value = set, explicit `null` = **reset to `link.created`**. The usual `?? null` serialisation of an optional field is therefore a destructive write that moves the row to another calendar day in every `occurred_at` ordering.
**Root Cause**: An input that doubles as a patch payload invites partial construction sites; "absent" had no safe meaning before the tri-state, and `null` (formerly "clear this optional field") had to be redefined for a `NOT NULL` column.
**Fix**: _Documented, not structurally enforced._ The contract is in the comment on `SocialMediaLinkInput.occurred_at` (`incident/schema/inputs.py`) and the service's branch comments, pinned by `tests/incident/test_social_link_occurred_at_write.py` (`UpdateOccurredAtTests`, `OccurredAtMutationTriStateTests`). The GraphQL layer maps `Maybe` to the service sentinel by hand (`OCCURRED_AT_UNSET if not input.occurred_at else input.occurred_at.value`) because `Some.__bool__` is always `True`. Every construction site was audited in the same change.
**Prevention**: Adding a field to a replace-not-patch input changes **every** caller: grep every construction site and confirm each re-sends the field or may reset it. Treat `null` as a value with meaning; never let a `?? null` default stand for "unchanged". The structural fix (a separate patch input) is not done; treat replace semantics as a known sharp edge.

### [2026-09-26] incident: every stored datetime is naive **local** time (`USE_TZ = False`) — axis of two traps

**Problem**: With `USE_TZ = False` and `TIME_ZONE = "Asia/Kuala_Lumpur"` every stored datetime is naive local wall time. Two surfaces made that internal convention an external hazard (second surface found 2026-09-30):

- **Export**: `manage.py export_official_posts` writes `posted_at` as the stored column's own `isoformat()`, so a post the X API reported as `2026-09-26T03:15:00Z` exports as `2026-09-26T11:15:00`, a true instant with no offset, in a file meant to leave this system. The `--since`/`--until` window is unaffected (aware bounds convert into the same storage frame).
- **Migrations**: `0030`'s `occurred_at = COALESCE(posted_at, created)` must be a straight byte copy. The obvious Python loop (`link.occurred_at = link.posted_at or link.created` + `bulk_update`) round-trips every value through the field adapter and shifts the table by +08:00, invisible at minute precision and later visible as links ordered into the wrong calendar day against `currentServiceDayOnly` / `lastWeekOnly`.

**Root Cause**: `USE_TZ = False` makes the storage frame an application convention, not a DB guarantee: nothing raises or warns, and the naive value looks right everywhere it is read. A per-row Python loop is the usual shape of a Django data migration and the one shape that silently re-interprets stored bytes.
**Fix**: _By design, documented._ The exported value is the stored column verbatim (spec §6.1); consumers re-anchor with `settings.TIME_ZONE`. `0030` uses `update(occurred_at=Coalesce("posted_at", "created"))` (reverse: `update(occurred_at=F("created"))`) and its docstring bans `make_aware`/`make_naive`/`astimezone`/`localtime`. Values are pinned by literal in `tests/incident/test_social_link_occurred_at_backfill.py` and `test_official_post_occurred_at.py`.
**Prevention**: When a value crosses the app boundary (export, GraphQL, webhook), decide between "the stored value" and "the same instant in UTC" and pin it with a docstring and a test. A migration copying a datetime between columns is one SQL expression (`Coalesce`, `F`), never a loop. Do not "repair" a `posted_at`/`occurred_at` divergence by converting one into the other: both come from the same `RawPost.posted_at` on the automated path, so `make_aware`/`astimezone` would double-shift every post; the only legitimate divergence is the `Some(None) → link.created` reset. If `USE_TZ` ever flips to `True`, re-check the export: strings gain an offset and published datasets shift.

### [2026-09-30] incident: the keyset cursor is field-agnostic — a stale token still decodes

**Problem**: `incident/schema/keyset.py` encodes a timestamp and a row id and **no column name**:

- **(a) A cursor minted before a column change still decodes.** A pre-`0030` token (a `created` timestamp) is accepted by the post-`0030` resolver and silently means "resume after this `occurred_at`": skipped or repeated rows, no error. The same applies to `CalendarIncidentScalar.links`, and the frontend can hand a nested page-1 cursor to the root query, so one stale token crosses surfaces.
- **(b) The helper serves two columns.** `SocialMediaLink` orders on `occurred_at` (root `publicSocialMediaLinks` and nested `CalendarIncidentScalar.links`); `get_line_status_reports` orders on `LineStatusReport.created` (deliberately: a report *is* its creation instant). Names and parameters are not field-specific, so a copied resolver can silently paginate the wrong column. Re-checked 2026-10-01: the link-tree wave changed `Meta.ordering`, page composition (`collapseThreads` narrows to roots *before* the cursor) and added a sort-free nested `sublinks` but left both sort columns alone, so it is not a new instance. `sublinks` has no `first`/`after` and mints no cursor (depth bounded by write-side `MAX_THREAD_DEPTH`); a paginated sublink field would be a *third* consumer and a third review of this entry.

**Root Cause**: One wire format shared across surfaces is the right design (it lets the frontend hand a nested cursor to the root query), but "which column is this?" is a caller property enforced only by convention, and changing a sort column changes the meaning of an opaque token, which cannot signal that.
**Fix**: _Not fixed — accepted, documented._ `get_public_social_media_links`'s docstring says in-flight cursors across the deploy are not guaranteed seamless and the feed should restart from page one; `keyset.py`'s module docstring names both consumers and states hazard (a) ("an opaque payload for one column is happily accepted by a consumer on another").
**Prevention**: (a) Changing a cursor's sort column requires a **versioned encoding** (`"o1:"`/`"c1:"`, rejected loudly on mismatch) or **forcing clients back to page one**; when reviewing an `.order_by()` change on a paginated resolver, inspect every producer of its cursors. (b) When copying the helpers into a new resolver, rename local variables to the column actually ordered on and add the resolver to the `keyset.py` docstring, which makes the consumer count checkable from one file. A third column needing its own cursor is the moment to version the encoding.

### [2026-09-30] tests: `created` is stamped from the real clock — neither `create(created=…)` nor patching `timezone.now` moves it

**Problem**: Tests needing a `SocialMediaLink` / `LineStatusReport` (any `TimeStampedModel`) at a given `created` cannot use `create(..., created=<datetime>)`: `auto_now_add` ignores it, every row gets "now", day-grouping assertions collapse into one day and the test passes for the wrong reason. Recurred 2026-10-03: with `django.utils.timezone.now` patched to `2026-10-03 00:05`, `LineStatusReport.objects.create(...)` stored `created = 2026-10-03 00:15:48` (the real clock) while `service_day_start(...)` resolved against the frozen time, so `assertEqual(len(buckets), 24)` failed with `0`, indistinguishable from the 03:00-rollover trap being audited. Patching to an instant later than the real clock is no workaround: a row stamped before 03:00 real time then falls outside the frozen day.
**Root Cause**: `model_utils/fields.py` does `from django.utils.timezone import now`, so `AutoCreatedField.pre_save` (every `TimeStampedModel.created`) calls a captured function object that patching the `django.utils.timezone.now` attribute cannot reach; a plain `models.DateTimeField(auto_now_add=True)` calls `timezone.now()` and *is* patched (verified with `inspect.getsource`). Only `QuerySet.update()` writes the column directly.
**Fix**: Create, then stamp: `Model.objects.filter(pk=link.pk).update(created=<naive datetime>)` and `link.refresh_from_db()` (`PublicFeedContractTests._link`, `PublicFeedLastWeekAndDayAlignTests._link`); with `USE_TZ=False` the value is naive Asia/Kuala_Lumpur and maps onto the day the resolver groups by. Service-day history fixtures set `created` explicitly this way; resolver-level tests that must use the loader's real `now` stamp rows on the **current hour**. No production change.
**Prevention**: Never expect `create(created=…)` to stick on a `TimeStampedModel`; insert then `.update()`. A frozen-clock run only proves anything for fixtures that set `created` explicitly or anchor to real now; when one fails, check the sign first (`created` later than the frozen `now`, or before the frozen day's 03:00, means the stamp, not the code). Assert day-grouping against distinct stamped days, not wall-clock now.

### [2026-09-12] rosak: the test-runner ground truth (ways the gate lies)

**Problem**: The documented test gate does not do what it says (items added through 2026-10-01):

- **`--parallel` is broken.** It crashes with `TypeError: cannot pickle 'traceback' object` as soon as any outcome carries a traceback, so a failing test surfaces as that pickling error instead of its own failure. The serial runner is the only reliable gate. CI (`.github/workflows/test.yml` Step 5) still runs `manage.py test --parallel --keepdb`: green while everything passes, a misleading `TypeError` on the first failure, and it never runs `tests/`.
- **`--keepdb` loses migration-seeded rows.** `TransactionTestCase` truncates tables, including rows from data migrations, and `--keepdb` never re-runs them: tests fail with `Clearance.DoesNotExist` and seed assertions. `get_or_create` what a test needs, or recreate the database.
- **Concurrent runs collide.** Two `manage.py test` runs share the single `test_postgres` database and truncate/recreate each other's tables. The wreckage looks like real failures: a storm of `common_vote.content_type_id` FK violations and dozens of `DuplicateDatabase` setup errors. Run one process at a time; suspect a collision before a code bug.
- **The top-level `tests/` tree is invisible to the bare run.** It has no `__init__.py`, so `manage.py test tests.operation` dies in discovery (`TypeError: expected str, bytes or os.PathLike object, not NoneType`) and plain discovery skips its pytest-style tests. pytest, `pytest-asyncio` and `pytest-django` are installed in the `app` container (`docker compose exec app python -m pytest tests/operation --collect-only -q` collects 11) but are **not declared** in `pyproject.toml`, `requirements.lock` or `requirements-dev.lock` (a rebuild from the lockfiles would lose them), and `pytest-cov` is absent; the host's system pytest lacks the plugins (`python3 -m pytest tests/incident --collect-only` → 7 collected, 40 collection errors). Full dotted module labels *do* resolve under the Django runner (`manage.py test tests.incident.test_social_link_threads --keepdb`).
- **Each wave of `tests/` modules widens the blind spot.** 2026-09-30: six modules under `tests/incident/` (119 test functions by AST) were invisible to the bare run. 2026-10-01: three more (`test_social_link_tree_model` 27, `test_social_link_tree_migration` 13, `test_social_link_position_field` 16), and 192 tests green across the seven incident modules by full dotted label, none of them in the bare 494-test run. A red bare gate is evidence about the app modules; silence is evidence about nothing in `tests/`.

**Root Cause**: `tests/` is a namespace package, so Django's label discovery cannot resolve it and plain discovery skips it; nothing enforces that a suite joins a gate.
**Fix**: _Workaround._ Runnable tests live in app modules (`operation/tests.py`, `incident/tests.py`, `rosak/tests/…`) and run by app label (`manage.py test operation incident rosak`). `tests/` tests run by full dotted label under the Django runner, or under the container's pytest (then rebuild the test DB, see the 2026-10-19 entry); declaring pytest in the lockfiles or adding an `__init__.py` would make them part of the gate.
**Prevention**: **A new backend test nobody's gate runs is not a test.** Put it where `manage.py test` collects it (app `tests.py` / `rosak/tests/`), or run it by its **full dotted module label** in the same change and say so in the progress entry. Never report "N tests added" without the command that executes them. Use the serial runner locally and when triaging a CI failure, because `--parallel` hides the real error behind the pickling `TypeError`.

### [2026-09-28] incident: the official-post poll's opt-in is read twice with different lifetimes — only `celerybeat` dispatch sees it

**Problem**: `OFFICIAL_POST_POLLING_ENABLED` (default off) is read in two places. `rosak/celery.py` builds `beat_schedule` **at import**, so toggling the env var and restarting only `celeryworker` changes nothing: the 5-minute `ingest_official_posts` tick keeps running (or never starts) until `celerybeat` restarts. `incident/tasks.py` re-reads the setting every run, so a manually enqueued run and a beat-dispatched run can disagree with the value just toggled.
**Root Cause**: The schedule is a module-level dict evaluated once at import; the task guard is a per-run read. The two layers (dispatch gate + execution gate) are deliberately independent, which makes "did my env change apply?" ambiguous if only one service restarts.
**Fix**: _By design, documented._ The settings comment and the `docs/APPS.md` beat table state that toggling needs a `celerybeat` restart. Verify with `docker compose exec app python -c "from rosak.celery import beat_schedule; print('ingest_official_posts' in beat_schedule)"` after the restart.
**Prevention**: Every new env-gated beat entry states the restart requirement in its settings comment and the APPS.md beat table; never verify a schedule toggle by looking at the worker alone.

### [2026-09-28] tests: the debug toolbar breaks every `self.client` request, and the cache is Redis

**Problem**: All 30 `XWebhook*` tests errored with `NoReverseMatch: 'djdt' is not a registered namespace`, and handle-resolution tests failed like a logic bug (a cache hit from a previous run changed the answer). Two environment traps that contradict the docs.
**Root Cause**: (1) `DEBUG_TOOLBAR_CONFIG["SHOW_TOOLBAR_CALLBACK"]` closes over the **module global** `DEBUG` (true in dev) while the test runner sets `settings.DEBUG = False`: `rosak/urls.py` withholds the `djdt` routes, but the middleware (inserted at import while `DEBUG` was true) still renders and `_postprocess` reverses `djdt:render_panel` unconditionally. (2) `CACHES["default"]` is `RedisCache`, **not** `DummyCache` (the swap only applies when `DEBUG` is true, and this environment is the opposite); user-id caches used `timeout=None`, so keys survived across runs and test classes.
**Fix**: Client-based test classes carry `@modify_settings(MIDDLEWARE={"remove": ["strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"]})` (inline in `operation/tests.py` and `rosak/tests/test_version.py`; alias `no_debug_toolbar` in `incident/tests.py`). The cache-hit instance went away when handle resolution moved to the account registry (`services/x_webhooks.py::_resolve_account`; `_resolve_user_id` no longer exists), but the lesson stands for any cached lookup.
**Prevention**: Any new test class using `self.client` needs the toolbar removed. Any test whose assertions depend on a cache *hit* must pin `CACHES` to a private `LocMemCache` with its own `LOCATION` and not reuse a cached key across tests. Do not trust the `DummyCache` note for this environment; check `settings.CACHES` first.

### [2026-09-26] incident/telegram_provider: an outbound audit row with no `payload["message"]` is silently un-approvable

**Problem**: `handlers.approve` resolves a replied-to message by JSONB lookup on `telegram_log__payload__message__message_id` + `__chat__id`. That block is written by `views.TelegramInbound` for **inbound** rows, so an admin replying `/approve` to an official-post notification got the generic "No media awaiting review found for this message." — indistinguishable from replying to an ordinary chat message, with no hint the notification was real.
**Root Cause**: `TelegramLogs.payload` is a free-form `JSONField` with no constraint, and `send_message` created its OUTBOUND row *before* the send, so it had no `message` block. Nothing asserted that an outbound row is reply-resolvable.
**Fix**: `send_message` gained keyword-only `return_log=False`; when set it stamps `payload["message"]` (`message_id` + `chat.id`, mirroring the inbound shape) before `asave()` and returns `(message, log)`, which `incident.tasks._notify_new_link` joins to the `SocialMediaLink` via `TelegramSocialMediaLinkLog`. The default path deliberately does **not** stamp, so existing callers are unchanged. Tests: `SendMessageTests`, `ApproveHandlerTests`.
**Prevention**: Any new "reply to this message to act on it" feature must call `send_message(..., return_log=True)` and persist the returned log. If a reply handler reports "not found" for a message the bot demonstrably sent, check `TelegramLogs.payload->'message'` on that row before suspecting the handler.

### [2026-09-22] tests: entering async code and scoping assertions

**Problem**: Three ways a test asserted nothing or against the wrong row (last found 2026-09-26):

- **`asyncio.run` sees no test data.** `asyncio.run(handlers.approve(update))` inside a `TestCase` "found nothing" the test had just created: the async ORM ran on a different connection than the test transaction. `async_to_sync` passed with no other change (it runs on the calling thread, so the wrapping transaction applies). A sync `Model.objects.create` inside async code raises `SynchronousOnlyOperation`; use `acreate`/`asave`.
- **Patching an async symbol.** A `MagicMock` over an async function fails because `async_to_sync` awaits the *call result*: use a real `async def`/`AsyncMock`, and patch the symbol **where it is imported** (`incident.tasks.send_message`, not `telegram_provider.utils.send_message`). A module-level `from … import name` also defeats `mock.patch.object` on the source module.
- **`Vote` assertions were unscoped.** `Vote.objects.filter(object_id=…)` can match another content type's row (object ids are unique only per content type), making `tests/incident/test_chronology_mutations.py::test_chronology_upvote_changes_downvote` order-dependent. Not fixed: scope by `content_type` (ideally `user`); never treat `object_id` alone as identifying a vote.

**Root Cause**: Connection/transaction identity is invisible in test code, and identity is compound (`user`, `content_type`, `object_id`) where the assertion used one part.
**Fix**: Patch the admin check where it is looked up: `rosak.permissions.has_admin_claim` for function-local imports, the consumer module for module-level ones; never let a `MagicMock` user reach it unmocked (`51f2f69`). Use `async_to_sync`, never `asyncio.run`, to enter real async code from a `TestCase`.
**Prevention**: If a query inside async code "finds nothing" the test just created, suspect the connection, not the filter: assert a known-id lookup before rewriting the query. Always filter `Vote` assertions by `content_type`.

### [2026-09-24] telegram_provider: `error_handler` only prints and `/dadjoke` blocks the event loop (retry loop now bounded)

**Problem**: `/dadjoke` (`handlers.dad_joke`) does a blocking `requests.get` inside an async handler, blocking the event loop. `utils.infinite_retry_on_error` (a `while True` loop with 10s sleeps) could pin a worker forever, and `error_handler` only `print`ed because the admin alert path was commented out.
**Root Cause**: Ad-hoc resilience, a commented-out admin alert path and unbounded retries.
**Fix**: `0d1c3a4` (governed egress path): `infinite_retry_on_error` was replaced by the bounded `telegram_provider.utils.retry_on_error` (`max_retries=3`, exponential backoff), and `error_handler` now also sends the report to `TELEGRAM_ADMIN_CHAT_ID` through `send_message` when it is set (it still `print`s). Still open: `/dadjoke` blocks.
**Prevention**: Route all outbound messaging through the governed `send_message` path (logs `OUTBOUND`, splits at 4096 chars, dead-letters); make third-party fetches async or `sync_to_async`; every retry loop needs a bound.

### [2026-09-24] compose: recreate the credential-mounting services one at a time

**Problem**: `docker compose up -d` recreating `app` + `celeryworker` + `celerybeat` together intermittently fails with `OCI runtime create failed: ... not a directory: Are you trying to mount a directory onto a file (or vice-versa)?`; the affected containers exit 127/1 and the stack comes up half-dead.
**Root Cause**: Docker Desktop's WSL2 bind-mount backend races when the same host file (`~/.firebase/rosak-...json`) is bind-mounted into several containers created in parallel.
**Fix**: Recreate sequentially: `docker compose up -d --no-deps app`, then `--no-deps celeryworker`, then `--no-deps celerybeat`, then `docker compose restart web` (nginx caches the resolved upstream IP and exits if `app` is unresolvable at startup).
**Prevention**: Avoid single-command recreation of the app family on this setup.

### [2026-09-22] rosak: nginx keeps a stale `app` upstream after a container restart — 502 from :8000

**Problem**: After `docker compose restart app` the container gets a new IP but nginx (started earlier) keeps the old one, so `http://localhost:8000/` returns 502 while granian inside `app` is healthy.
**Root Cause**: nginx resolves the upstream hostname once at startup and caches the IP.
**Fix**: `docker compose restart web`.
**Prevention**: Restart `web` alongside `app` whenever `app`'s IP changes; don't debug the app when the failure is only visible through :8000.

### [2026-09-12] rosak: container-created migrations are root-owned and unwritable by the host user — WORKAROUND

**Problem**: `makemigrations` inside the container creates root-owned files. `./dev_permissioner.sh`'s `chown` fails for a non-root host user (it needs sudo), and pre-commit's `end-of-file-fixer`/`ruff-format` then fail with `PermissionError`.
**Root Cause**: The container runs as root while the host user owns the checkout; there is no in-band ownership handoff.
**Fix**: _Workaround._ From the repo root: `docker compose exec app chown -R $(id -u):$(id -g) .`.
**Prevention**: Re-own container-generated files right after `makemigrations`, before any hook or `ruff format`.

### [2026-09-15] common: S3 uploads fail on OCI Object Storage — "AWS chunked encoding not supported"

**Problem**: Every `TemporaryMedia` save (incl. Telegram image attaches via `POST /upload/`) raised `botocore.exceptions.ClientError ... PutObject: AWS chunked encoding not supported.` Uploads reached OCI but were rejected with 501.
**Root Cause**: botocore >= 1.35 defaults `request_checksum_calculation` to `when_supported`, adding a CRC32 trailer (`Transfer-Encoding: chunked` + `Content-Encoding: aws-chunked` + `X-Amz-Trailer`) that OCI's S3-compat endpoint rejects. `AWS_S3_SIGNATURE_VERSION="s3v4"` does NOT help (already the default); this is a checksum-trailer issue, not a signature issue.
**Fix**: `os.environ.setdefault("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required")` in `rosak/settings.py`, so `PutObject` goes out as a plain body (verified botocore honors it on the django-storages client).
**Prevention**: Any botocore/boto3 bump must re-check this; if uploads regress with this error, re-apply `when_required`. `AWS_S3_CLIENT_CONFIG={"request_checksum_calculation": ...}` as a plain dict crashes botocore in django-storages 1.14.6; only the env var or a `botocore.config.Config` instance works.

### [2026-08-24] common: `ImgurStorage` — write path hot on every upload + silent credential failure

**Problem**: Two coupled defects left over from the Imgur → Discord migration:

- **Hot path**: `common/tasks.py` (`convert_temporary_media_to_media_task`) creates `Media` with `file=ContentFile(temp_media.file.url, …)`, routing every upload through `ImgurStorage._save` and a live Imgur API call, although `Media.file` is marked `# TODO: Deprecate` and Discord CDN is the real host.
- **Silent degrade**: `ImgurStorage.__init__` and the module-level `ImgurClient` swallow all exceptions and print `functionality disabled`; the `IMGUR_*` settings default to `""` (`rosak/settings.py`), so a deployment without credentials dies with `AttributeError` inside a broad `except Exception` and only increments `fail_count`: no upload can succeed although Discord is the host.

**Root Cause**: The migration left `Media.file` wired as the write path and never removed its five call sites (`STORAGE = ImgurStorage()`, `MediaMixin.__str__`, `add_width_height_to_media_task` filter, `medias_group_by_period ~Q(file="")`, `MediaAdmin.fields`). Fail-open init plus a broad exception hides the root error.
**Fix**: _Not fixed._ Needs a re-host backfill for pre-`0013` rows (fetch `i.imgur.com/<file>` → Discord webhook → fill `file_id`/`file_name`), then drop `Media.file` and delete `imgur_field.py`, `imgur_storage.py`, `management/commands/get_imgur_token.py`. Meanwhile make init fail loudly if `Media.file` is still required.
**Prevention**: Feature-flag the storage backend; block new `Media.file` writes behind the flag and alert on `ImgurStorage._save` after a cutoff. Validate required credentials at `check` time; never swallow storage init errors; replace the broad `except Exception` with typed handling plus an explicit dead-letter.

### [2026-08-24] common: a missing or disabled `FeatureFlag` silently disables uploads — and gates the GC

**Problem**: `should_upload_media()` (`common/utils.py`) is `feat_flag is not None and feat_flag.enabled`, so a missing row or the default `enabled=False` means off. `cleanup_temporary_media_task` early-returns on that same flag, so disabling uploads also halts the 30-day `TO_DELETE` GC and the staging bucket grows unbounded.
**Root Cause**: Ambiguous "missing = off" plus coupling the upload gate to garbage collection.
**Fix**: _Partly fixed._ Migration `0016_featureflag_alter_media_file_data` seeds one disabled row per `FeatureFlagType`; a row missing later (e.g. truncated by a `TransactionTestCase`) still reads as off. Still open: split the GC flag from the upload flag.
**Prevention**: Separate `IMAGE_UPLOAD` vs `STORAGE_GC_ENABLED` flags; tests needing the flag `get_or_create` it.

### [2026-08-24] common: `Media` scalar non-null mismatch

**Problem**: `MediaScalar`/`MediaType` (`common/schema/scalars.py`) declare `width: int` / `height: int` non-null while `Media.width`/`height` are `null=True, default=None`, so exposing more rows raises non-null resolution errors on legacy media.

- **Recurrence 2026-10-21, `MediaType.file`.** It is non-null, but `Media.file` is `''` on 417 of the 2,856 rows of the dev DB (restored from a dump; production unverified): all dated 2023-10-21 to 2024-03-13, all with the Discord `file_id` / `file_name` set (the cause is presumably a failed legacy Imgur write; unverified). Any `medias` page that contains one returns `data: null` with `Cannot return null for non-nullable field MediaType.file.` The newest such row is at offset 650 of `created DESC`, so the feed fails from page 28 at 24 per page (page 7 at 100). The new `media(id)` returns `null` plus the same error for such a row, because it uses the same type. `MediaType` has no `url`, so the Discord CDN address (`Media.url`, which `MediaScalar` does expose) is out of reach. The gallery frontend already null-checks `file`.

**Root Cause**: Scalar nullability was not matched to the model.
**Fix**: _Not fixed._ Make the scalar widths `Optional[int]` or backfill dimensions. For `file`: `Optional[DjangoFileType]` plus a `url` field on `MediaType`. The nullability change is a breaking change by graphql-core's rules, so it needs an entry in `EXPECTED_ACCEPTED_BREAKING_CHANGES` (`rosak/tests/test_schema_snapshot.py`, count pinned) and a regenerated snapshot.
**Prevention**: Contract test asserting model nullability matches Strawberry scalar nullability.

### [2026-08-24] admin: ModelAdmin configuration defects

**Problem**: Five admin defects, one theme: the admin is never smoke-tested.

- `common.TemporaryMediaAdmin.prettified_metadata` calls `self.prettify_json()` but inherits `admin.ModelAdmin`, not `generic.admin.JsonPrettifyAdminMixin`, so it raises `AttributeError` (and has no `return`).
- `MediaAdmin` / `TemporaryMediaAdmin` use `search_fields = ["uploader"]` (an FK, not a text field), so admin search raises `FieldError`.
- `operation.LineAdmin` assigns `list_editable` twice; the second wins and drops `status` inline editing.
- `TemporaryMediaStatus.RETRY_ELAPSED` (`common/enums.py`) is assigned nowhere, so permanently dead uploads sit in `PENDING` indistinguishable from fresh rows. Assign it at `fail_count >= 5` and persist the exception string into `metadata` (`common/tasks.py`).
- `chartography.SourceCustomLine.mapped_lines` uses an explicit `through`, so Django omits it from the admin form; `SourceCustomLineLineMapping` is unregistered and `SourceCustomLineAdmin` has no inline, so the admin-editable reconciliation escape hatch is unreachable.

**Root Cause**: Missing mixin, FK used as a text lookup, duplicate attribute assignment, a dead status enum never wired into the retry cutoff, an explicit through not paired with an inline.
**Fix**: _Not fixed._ Inherit `JsonPrettifyAdminMixin` and return the highlighted HTML; `search_fields = ["uploader__nickname"]`; fix `list_editable`; wire `RETRY_ELAPSED`; add a `TabularInline` for the through model.
**Prevention**: Admin smoke test hitting every `ModelAdmin` change view (and creating a `SourceCustomLine` mapping through the UI); exhaustive status-transition test asserting every enum member is reachable; review `list_editable`/`search_fields` when an admin changes.

### [2026-08-24] resolvers & loaders: per-key batch state and per-node re-fetch

**Problem**: DataLoader/resolver shortcuts that silently return wrong or de-ordered data:

- `operation/schema/loaders.py::batch_load_vehicle_from_line` reads `keys[0][1]`, assuming every key in the batch shares the same `spotted_today` filter. Group keys by that filter before the query.
- `batch_load_spotting_count_from_vehicle` (`spotting_count_from_vehicle_loader`) aliases its aggregate on `key[0]` only while the key is `(vehicle_id, Q(date_filter))`, so two date windows for one vehicle in one request collide and return the same count. Alias on the full composite key.
- `incident/schema/loaders.py::batch_load_medias_from_calendar_incident` returns a `set` though the field is typed `List[MediaScalar]`, so media are silently de-duplicated and the through-table `timestamp` ordering is discarded. Return a `list`.
- `CalendarIncidentScalar.last_updated` re-fetches its row, then `.count()` + an ordered slice on `chronologies`: 3 extra queries per node, invisible to `DjangoOptimizerExtension` (the app's N+1 hotspot). Annotate with `Greatest(F("modified"), Max("chronologies__modified"))` or batch.
- `batch_load_location_event_from_event` keeps the last `LocationEvent` row silently, because `event` is a FK, not a OneToOne (see the spotting `LOCATION` entry).

**Root Cause**: Batch keys carry filter state the SQL alias ignores; "ergonomic" `keys[0]` shortcuts; collection type chosen without the ordering contract; resolvers re-fetching per node.
**Fix**: _Not fixed._
**Prevention**: Never index `keys[0]` for per-key state; include the whole key in any SQL alias; type-check loader return shapes against the field type; load-test with `assertNumQueries` and forbid per-node re-fetch in resolvers.

### [2026-08-24] incident / operation: duplicate `Line ↔ CalendarIncident` join tables — GraphQL field permanently empty

**Problem**: `CalendarIncident.lines` (`related_name="incidents"`, migration `0013`) and `operation.Line.calendar_incidents` are two separate M2M join tables. Admin `filter_horizontal` edits the former; GraphQL `Line.calendarIncidents` reads the latter, so that field is expected to be permanently empty. (`LineAdmin.exclude = ("calendar_incidents",)` only hides the unused side from the Line admin page.)
**Root Cause**: Both sides declared `ManyToManyField` to each other instead of one side using the reverse accessor; `through` was left commented on `Line`.
**Fix**: _Not fixed._ Consolidate on the `Line.incidents` reverse accessor and remove `Line.calendar_incidents`.
**Prevention**: Single source of truth for cross-app M2M; reject duplicate M2M declarations across apps in review or a CI lint.

### [2026-08-24] incident: `CalendarIncidentFilter.date` month off-by-one (bare assert since fixed)

**Problem**: The `month` branch (`incident/schema/filters.py`) does `start_datetime__month__lte = month_exact + 1` (and the same `+ 1` on `end_datetime__month__gte`), assuming a 0-indexed JS month. Range width was also enforced with a bare `assert … <= timedelta(days=60)`: a 500, and stripped under `python -O`.
**Root Cause**: JS month indexing leaked into Python; `assert` used for validation.
**Fix**: _Partly fixed._ `8c0eff5` replaced the `assert` with `GraphQLError("date range cannot exceed 60 days")`. The `+ 1` arithmetic is still there.
**Prevention**: Ban bare `assert` for request validation (repo convention); add filter unit tests for the 60-day boundary and for `month` exact against a known month.

### [2026-08-24] operation: write-API scaffolding references non-existent modules + scalar mismatches

**Problem**: Commented `operation/schema/inputs.py` does `from operation.schema.enums import AssetType`, but that module does not exist (enums live in `operation/enums.py`). `StationInput.internal_representation` is a `StationLine` field misplaced on `Station`; no `VehicleInput` exists. In the read schema, `VehicleType` declares `info: str` while the model field is `description`, and `Asset.stations` / `StationLine.lines` declare plural lists over singular FKs.
**Root Cause**: A refactor moved the enums but the inputs stub was not updated; `Station` vs `StationLine` confusion; copy-paste scalar naming.
**Fix**: _Not fixed._ Repoint the import to `operation.enums` or the generated enum; drop/nest `internal_representation`; add `VehicleInput`/`VehiclePartialInput`; rename scalar fields to match the model.
**Prevention**: Keep commented scaffolding importable under `if TYPE_CHECKING`; `ruff check` still covers commented files; generate scalar names from the model.

### [2026-08-24] operation: `StationLine` has no ordinal — lexicographic ordering breaks route order

**Problem**: `StationLine.Meta.ordering = ["internal_representation"]` sorts lexicographically (`KJ10` before `KJ2`) and there is no `order` field, so `Line.station_lines` cannot render travel order for strip maps / "next stations".
**Root Cause**: Missing `OrderedModel` although `django-ordered-model` is already a dependency (used by `incident`).
**Fix**: _Not fixed._ Inherit `OrderedModel` with `order_with_respect_to="line"`, data-migrate `order` from the numeric tail of `internal_representation`, switch the admin to `OrderedTabularInline`.
**Prevention**: Explicit route-order field; never rely on code-string ordering for sequence.

### [2026-08-24] spotting: `LOCATION` payload invariants are unenforced; deletion policy duplicated

**Problem**:

- `spotting_event_value_relevant` governs only station columns (it groups `LOCATION` with the no-station types), so `type=LOCATION` can be saved with no `PointField`; GraphQL `add_event` only creates a `LocationEvent` when a location input is supplied, making the type decorative.
- `LocationEvent.event` is a `ForeignKey`, not a `OneToOne`; the loader keeps the last row silently.
- The deletion rule is expressed twice: `Event.auser_deletion()` raises, while the `deleteEvent` mutation returns `ok=False` with a subtly different 3-day window (`created__gte=now()-3d`).

**Root Cause**: The constraint models station invariants only; FK chosen without uniqueness; policy expressed as a queryset filter in two places instead of one model method.
**Fix**: _Not fixed._ Extend the `CheckConstraint` (or validate in the mutation) to require a `LocationEvent` for `type=LOCATION`; migrate to `OneToOneField` after dedup; hoist the window into `Event.is_within_edit_window()` used by both paths.
**Prevention**: DB-level invariant tests per `SpottingEventType`; `OneToOneField` for 1:1 payloads; one model method for policy.

### [2026-08-24] spotting: `eventsCount` unfiltered + `with_most_entries` IndexError

**Problem**: `spotting.schema.resolvers.get_events_count` is a bare `Event.objects.acount()` ignoring `EventFilter`, so a paginated UI shows the wrong total. `common` `UserScalar.with_most_entries` indexes `[0]` into an aggregate queryset and raises `IndexError` for a user with zero events.
**Root Cause**: The count resolver does not reuse the filter `Q`; missing empty-queryset guard.
**Fix**: _Not fixed._ Pass the filtered queryset into the count; guard `with_most_entries` with an empty check (the commented `ListConnectionWithTotalCount` is the intended fix).
**Prevention**: Derive a count from the same filtered queryset; test the zero-event user profile.

### [2026-08-24] common / telegram_provider: JSONB lookups must match the stored shape and be fully qualified

**Problem**: Two ways a JSONB lookup silently matches nothing (the unstamped-outbound-row case is the 2026-09-26 entry above):

- **Types survive into JSONB.** `TemporaryMedia.metadata` stores Telegram `message_id`/`chat_id` as ints, so `Q(metadata__telegram_message_id=source.message_id)` only matches int-vs-int; a stringified id silently matches nothing and `approve()` reports no media awaiting review.
- **Unqualified `message_id`.** `handlers.spot` and `handlers.submit_link` find the inbound `TelegramLogs` row by `payload__message__message_id` with no `__chat__id` filter (unlike `/delete`, `/deletelink`, `/approve`), so message ids, unique only per chat, can bind spotting provenance to another chat's message. `payload` has no DB index (no `Meta`).

**Root Cause**: `JSONField`/`JSONB` lookups preserve the stored Python type and are not schema-checked; nothing enforces that an id lookup includes its scoping key.
**Fix**: _By design / not fixed._ Store native ints and compare with the native type; add the `payload__message__chat__id` filter to `spot`/`submit_link`, a `UniqueConstraint(spotting_event, telegram_log)` and a GIN/expression index on `payload`.
**Prevention**: Always qualify a Telegram `message_id` with `chat_id`; index JSONB lookups used in production queries; add a round-trip test asserting the stored type matches the lookup argument's type.

### [2026-08-24] telegram_provider: `/approve` admin identity needs a linked user + Firebase claim — GOTCHA

**Problem**: `approve()` resolves `common.User` by `telegram_id`, then checks `has_admin_claim`. An admin who never ran `/verify` has no `User` row and is rejected before the claim is consulted.
**Root Cause**: The handler reuses the "verified Telegram user" precondition of the other commands and layers the admin claim on top.
**Fix**: _By design._ Resolve the user first, then call `has_admin_claim`; the import is function-local to avoid an app-loading cycle.
**Prevention**: Document that admin bot commands require a linked `User` (`/verify`) in addition to the Firebase admin claim.

### [2026-08-24] chartography: MTREC task ignores `force`/`triggered_by_id`, and drops corrections

**Problem**: `aggregate_line_vehicle_status_mtrec_task(self, *args, **kwargs)` accepts but ignores `force` and `triggered_by_id`, and no mutation triggers it (the MLPTF task has the kwargs and a mutation). `force` is a dead parameter on both tasks, and `bulk_create(ignore_conflicts=True)` discards corrections. (`SourceCustomLine`'s unreachable admin mapping is in the admin entry.)
**Root Cause**: The MTREC path was not given the same kwargs as the MLPTF path.
**Fix**: _Not fixed._ Give the MTREC task `force`/`triggered_by_id` plus a sibling mutation; wire `force=True` to delete conflicting `Snapshot` rows inside `transaction.atomic()`.
**Prevention**: Mutation parity test for both sources.

### [2026-08-24] chartography: hardcoded PK map + implicit datetime coercion + assert guard

**Problem**: MTREC `short_code_line_ids_map` hardcodes numeric `operation.Line` PKs (`KGL→[2]`, `Komuter→[13,14]`), which rot on reseeding. `Snapshot.date` (a `DateField`) is assigned a `datetime` (`now() - timedelta(...)`), relying on implicit coercion that is timezone-sensitive at day boundaries. `Snapshot.url` is never populated. The shape guard is `assert isinstance(line_ids, list)`, stripped under `python -O`.
**Root Cause**: Seed-data assumptions baked into code; strict validation left as an assert.
**Fix**: _Not fixed._ Always write `custom_line_id` and resolve via the `custom_line__mapped_lines` join seeded by a data migration; use `.date()` explicitly in the defined timezone; raise an explicit exception for an unknown short code; populate `Snapshot.url`.
**Prevention**: Forbid hardcoded PKs; validate external payload shapes with explicit errors, not `assert`.

### [2026-08-24] reporting: dormant GraphQL layer — enums, uniqueness, authz

**Problem**: The `reporting` app is parked with a broken surface:

- `reporting/schema/filters.py` and `inputs.py` import `reporting.schema.enums`, which does not exist; `Report.type` is a plain `TextField(choices=...)`, so `strawberry.auto` renders `String`, not the `ReportType` enum.
- `ReportFilter.filter_types` filters `report_type__in` while the model field is `type`; no `UniqueConstraint` on `Vote(report, user)` (repeated `createVote` stuffs the ballot), and the same missing uniqueness on `ReportMedia`/`ReportResolution` allows duplicate attachments/links (compare `operation.AssetMedia`).
- Auto-generated `delete_reports` / `delete_vote` carry no `permission_classes`, and `VoteInput.user_id` / `ReportInput.reporter_id` are client-supplied, so any caller can vote or file as any user.

**Root Cause**: The scaffolded GraphQL layer was never completed; the model used plain choices instead of `TextChoicesField`; authz was never reviewed.
**Fix**: _Not fixed._ Create a Strawberry enum over `reporting.enums.ReportType` per `generic/schema/enums.py` and switch `Report.type` to `TextChoicesField(choices_enum=…)`; fix the filter to `type__in`; add uniqueness plus an idempotent `toggle_vote` deriving `user_id` from `info.context.user.id`; derive voter/reporter server-side and gate mutations `IsLoggedIn+IsRecaptcha` with owner-delete checks.
**Prevention**: Never trust a client-supplied `user_id`; unique constraint on every vote/through table; CI import-check even for dormant apps.

### [2026-08-24] generic: `GeometricForm` dead `required` + shared-`Meta` mutation + `longitude==0` dropped

**Problem**: In `generic/views.py`, `GeometricForm.required` is `None` (falsy) but `latitude`/`longitude` are built in the parent class body with `required=required` while it is still `None`, so a subclass's `required=False` is never read. Subclasses configure by mutating the parent's shared `GeometricForm.Meta` (e.g. `GeometricForm.Meta.model = Station`; `Meta.widgets={"location": HiddenInput()}` in `incident` but commented out in `spotting`/`operation`), so whether `location` renders hidden depends on import order. `clean()` does `if latitude and longitude`, so a legitimate `longitude==0` (prime meridian) is silently dropped.
**Root Cause**: Class-attribute mutation instead of per-subclass `Meta`; truthiness check instead of `is not None`.
**Fix**: _Not fixed._ Move model/widget config into per-subclass `Meta` or an `__init_subclass__` hook; build the fields in `__init__` from `self.required`; change `clean()` to `if latitude is not None and longitude is not None`.
**Prevention**: Never mutate a parent `Meta`; add a `longitude=0` test case.

### [2026-08-24] generic: `generic/schema` has no `__init__.py`, and `generic/types.py` is dead code

**Problem**: `generic/schema` is an implicit namespace package (no `__init__.py`), and `generic/types.py`'s `Point2D` TypedDicts (`Point2D_SearchField`) are unused. Two earlier defects here are fixed: `WebLocationInput` fields were `Optional[float]` with no default, making the `UNSET` branch in `spotting/schema/schema.py` unreachable (`bb1e519` moved them to `Maybe[float | None] = strawberry.UNSET`), and `generic/tests.py` was empty (it has tests since `c318fd4`). The field-less `GenericScalars`/`GenericMutations`/`PublicSpottingStats` types no longer exist.
**Root Cause**: Incremental scaffolding left incomplete.
**Fix**: _Not fixed._ Add `__init__.py`; promote `Point2D_SearchField` to a real `@strawberry.input` with a shared `Q`-builder for point-radius search (needed by `operation`, `spotting`, `incident`), or delete it.
**Prevention**: Require `__init__.py` for every `schema` package; test that `strawberry.UNSET` branches are reachable.

### [2026-08-24] rosak: `DEBUG=True` swaps Redis for `DummyCache` + disables the introspection guard

**Problem**: Local `DEBUG=True` replaces the Redis cache with `DummyCache`, and the `NoSchemaIntrospectionCustomRule` is added only when `DEBUG=False`, so cache bugs are not reproducible locally. The 2026-09-28 test-env entry shows the inverse (a `DEBUG=False` environment with real Redis), so **check `settings.CACHES` rather than trusting this note**.
**Root Cause**: Dev convenience swallowing the cache layer; the introspection gate is coupled to `DEBUG`.
**Fix**: _Not fixed — by design._ Use a `DummyCache`-aware test harness or run with `DEBUG=False` locally for cache repro.
**Prevention**: CI runs with a prod-like cache; add an integration test toggling `DEBUG`.

### [2026-08-24] rosak: `common/tasks.py` circular import hazard

**Problem**: `common/tasks.py` imports `spotting` and `incident` at module top level (`from incident.models import CalendarIncidentMedia`, `from spotting.models import Event, EventMedia`) while both apps import `common`: a genuine cycle, and the reason most other imports in that file are function-local.
**Root Cause**: The task needs cross-app models but lives in `common`.
**Fix**: _Not fixed._ Lazify the imports or move task ownership to a leaf app.
**Prevention**: Add an import-cycle gate to CI (no `tach.yml` exists in the repo today); prefer lazy string refs and function-local imports for cross-app models.

---

## Fixed

Historical fixes with no live action; kept so the ground isn't re-covered. Full detail in git.

- **2026-10-21** — `spotting`: an anonymous spotting hid its reporter but not its position. Anonymity was enforced only in `reporter_from_event_loader` (`is_anonymous=False`), so `events(filters: {isAnonymous: true, type: {exact: "LOCATION"}}) { location { location accuracy } }` returned full-precision coordinates to a logged-out caller. `EventScalar.location` now resolves to `null` for an anonymous event unless the viewer is its reporter or an admin (`viewer_can_see_location`); the admin claim is read once per request through `common`'s `is_admin_from_user_loader`. `LocationEvent` is returned by that one field only and `EventFilter` has no location lookup; `AnonymousLocationVisibilityTests` fails if a second path or a location filter appears. **Anonymity is per field, not per event: any new field that carries a reporter-linked value (position, photo EXIF, notes) must go through the same gate.** Photos already uploaded to Discord keep their EXIF GPS (see the upload-strip entry).
- **2026-10-21** — `spotting`: `report_spotting_today` never sent a digest. `Line.objects.distinct("telegram_channel_id")` raised `ProgrammingError: SELECT DISTINCT ON expressions must match initial ORDER BY expressions` on every run, because `Line.Meta.ordering = ["code"]` led the ORDER BY. The task tests knew: they patched `spotting.tasks.Line` with an `_ordered_line_proxy()` shim "until the task declares it itself", so the suite stayed green while production failed nightly. The DISTINCT ON is intended (lines sharing a route and fleet share one channel and get one digest, for the first line by code), so the task now orders by `("telegram_channel_id", "code")` first, and `Line.telegram_channel_id` is no longer unique (migration `0018`), since the uniqueness made sharing impossible. The shim is gone, so `ReportSpottingTodayTaskTests` runs the real query, including `test_lines_sharing_a_channel_get_one_digest_for_the_first_line` (`6238a77`, `d0a2dd9`). **`.distinct(field)` on a model with `Meta.ordering` needs an explicit leading `order_by(field)`. Never patch around a production bug in a test; fix it or mark the test as an expected failure.**
- **2026-10-21** — `telegram_provider`: in a Celery worker, every send after the first in a process burned its first attempt on `NetworkError: Unknown error in HTTP implementation: RuntimeError('Event loop is closed')` (then succeeded on retry after a 2 s backoff). `async_to_sync` runs each `send_message` call on a fresh event loop and closes it, but `get_ptb_application()` cached the lazily built PTB app process-wide, and its httpx pool stays bound to the loop it was opened on. The lazy app is now cached per event loop in `utils._lazy_application`, apart from the lifespan's `apps.ptb_application` (`4a0ae91`). Pinned by `GetPtbApplicationTests.test_rebuilds_the_lazy_app_on_a_new_event_loop`. **An asyncio client cached across `async_to_sync` calls outlives its loop; key the cache by the running loop.**
- **2026-10-21** — `spotting` / `telegram_provider`: `report_spotting_today` (beat 00:00 local) passed `date.today() - timedelta(hours=12)`, which is `date.today()` (an hours-only `timedelta` is a no-op on a `date`), so the digest summarised the day that had just begun and bypassed the 03:00 service-day cutoff. It now uses `effective_spotting_date(datetime.now(ZoneInfo(TIME_ZONE)))`, which gives the day that just ended for any run before 03:00 (`f408119`). `get_daily_updates` also printed `date.today()` as its heading whatever `spotting_date` it got; the heading is now the spotting date (same commit). Pinned by `ReportSpottingTodayTaskTests.test_midnight_run_reports_the_day_that_just_ended` (patches only the task's own `datetime`; `timezone.now` patches do not move `auto_now_add`) and `GetDailyUpdatesTests.test_heading_is_the_requested_spotting_date`. **Never subtract an hours-only `timedelta` from a `date`; derive a service day from `effective_spotting_date`.**
- **2026-10-21** — `common`: `updateUser(input: {spottingDataPublic: null})` reached the `NOT NULL` column as `Some(None)` and raised `IntegrityError` (surfaced as an error response and a logged traceback). `UserInput.spotting_data_public` is now plain `Maybe[bool]`, so an explicit `null` is a coercion error (`cannot be explicitly set to null`) and omitted still keeps the stored value; the SDL stays `Boolean`. `nickname` is `str!`, so it had no hole. The frontend only ever sends a boolean (`d7890ba`). Pinned by `TestUpdateUserMutation.test_explicit_null_spotting_data_public_is_rejected`. **A `NOT NULL` column takes `Maybe[T]`, not `Maybe[T | None]`, unless `null` has a defined meaning (see `docs/STRAWBERRY_MIGRATION.md`).**
- **2026-10-21** — `telegram_provider`: `TELEGRAM_CLEANUP_DAYS` / `TELEGRAM_HTTPX_TIMEOUT` were read from the environment without conversion, so an env override was a string and `timedelta(days="7")` raised `TypeError` in `cleanup_telegram_logs`. They are now `int(...)` / `float(...)` in `settings.py` like the other numeric settings (`7ff07fa`; `TelegramSettingsEnvTests` reads them in a fresh interpreter). The task itself still does no coercion, by design.
- **2026-10-21** — `telegram_provider`: `parsers.ArgumentParser.error()` raised `ctypes.ArgumentError` (the foreign-function-call exception) and the handlers caught the same class, so it only worked by name coincidence. Both now use `argparse.ArgumentError` (`error()` raises `ArgumentError(None, message)`, so `str(e)` is still the bare message shown to the user) (`ab9f248`). Pinned by the `/spot` and `/link` bad-syntax handler tests.
- **2026-10-01** — `incident`: migration `0031` aborted with `psycopg2.errors.ObjectInUse: cannot ALTER TABLE "incident_socialmedialink" because it has pending trigger events` on any database with threaded links, so it was never recorded and the app served tree code against a `0030` schema (`column incident_socialmedialink.position does not exist`, the staging outage). `parent`/`thread` are `DEFERRABLE INITIALLY DEFERRED`, so the re-parenting `UPDATE` in the `RunPython` queued trigger events that fire at COMMIT while the next operation was DDL (`RemoveField(thread)` forward, `RemoveField(position)` reverse). Each half now ends with `SET CONSTRAINTS ALL IMMEDIATE` and `ExecutorRoundTripTests` replays the migration over a threaded row. **A data migration touching a deferred FK must flush queued checks before same-transaction DDL.**
- **2026-10-01** — `incident`: the nine vote mutations returned `GenericMutationReturn(ok=True)`, so the client projected the new score itself and raced its own echo plus other voters (the indicator "updated weirdly" and snapped back). They now return `VoteMutationPayload` (`ok` retained + `userVote`/`voteScore`/`upvotes`/`downvotes`) from one aggregate round-trip. The retype is breaking per graphql-core, so it is named in `EXPECTED_ACCEPTED_BREAKING_CHANGES` (15 entries) with a `_CHANGED_TYPE` description shape in the anti-rot test. **A mutation that changes a displayed aggregate must return the new value.**
- **2026-09-28** — `incident`: the X webhook read `includes` from the wrong envelope level (`payload.includes` instead of `data.includes`), so every real delivery was dropped; `_expansion_containers` now checks `data` first (`3f1723f`). Build webhook fixtures from a real captured body or the vendor schema, never by hand.
- **2026-09-28** — `incident`: `html.unescape` is applied once in `official_posts.tweet_to_raw_post`, so all ingest paths store decoded text while `RawPost.raw`/`raw_payload` stay encoded for export fidelity (`e099157`).
- **2026-09-26** — `incident`: auto-ingested `PENDING_APPROVAL` links no longer leak into the public feed (`exclude(is_automated=True, status=PENDING_APPROVAL)`); the exclusion stays scoped to `is_automated` so community pending rows remain visible. Approval: console queue or Telegram `/approve` (`a2f92ea`). Official ingestion now auto-publishes, so the exclusion is a defensive net for legacy rows.
- **2026-09-24** — `rosak`: `has_admin_claim` catches only `auth.UserNotFoundError` and returns False; other Firebase errors still propagate (`6a8f25e`).
- **2026-09-24** — `rosak`: a `rosak/tests.py` module shadows the `rosak/tests/` package and aborts discovery; use a `test_*.py` name (`bc45bf1`).
- **2026-09-24** — `operation`: `LineAdmin.exclude = ("calendar_incidents",)`; the auto-rendered M2M fetched every incident and was `blank=False` (`6ab47e8`).
- **2026-09-24** — `telegram_provider`: `/spotting_today` used the spotting enum's `NOT_IN_SERVICE` on `operation.Vehicle.status`; now `VehicleStatus.OUT_OF_SERVICE` (`6075118`).
- **2026-09-22** — `spotting`: Firebase credential bind-mounted from a nonexistent path made Docker create a root-owned directory; mount `${HOME}/…` and fail fast in `SpottingConfig.ready()` (`46cfde5`).
- **2026-09-22** — `compose`: `celerybeat`'s explicit `volumes:` replaces the YAML anchor's list (no deep merge for sequences); re-declare the credential mount (`2acbbc2`).
- **2026-09-22** — `incident`: `bucket_hourly` stopped at the current hour; it now returns all 24 service-day buckets, or `[]` when the line has no report in the day (`e1c64e1`).
- **2026-09-16** — `incident`: submitter link edits force `PENDING_APPROVAL` and are own-links-only, admin edits keep status, and an omitted `incident_id` preserves the association while an explicit `null` detaches it (`8bc4847`).
- **2026-09-16** — `telegram_provider`: with uploads disabled, `handlers.media` records the `TemporaryMedia` row (`metadata["uploads_disabled"] = True`) instead of dropping it; gate publication, not ingestion (`0882c80`).
- **2026-09-13** — `incident`: migrations `0015`/`0016` backfill pre-existing rows to `LIVE`; the `DRAFT` default governs only rows created afterwards (`038d23b`).
- **2026-09-12** — `common`: video conversion branches on `metadata["mime_type"]` and skips PIL/EXIF instead of raising `UnidentifiedImageError` (`82addcc`).
- **2026-09-12** — `rosak`: regenerate `rosak/tests/snapshots/schema.graphql` whenever GraphQL fields or types change (`0ff57ec`).
- **2026-08-24** — `common`: NSFW moderation re-enabled for non-trusted uploads, trusted clearance preserved (`1e2a421`).
- **2026-08-24** — `common`: `get_default_start_time()` uses `date.replace()` so YEAR/MONTH/WEEK no longer raise `AttributeError` (`bb1e519`).
- **2026-08-24** — `incident`: `StationIncident`'s `UniqueConstraint` gained `condition=Q(is_last=True)`, matching `VehicleIncident` (`1e2a421`).
- **2026-08-24** — `spotting`: `markAsRead` un-gated from `IsAdmin` to `IsLoggedIn` (`1e2a421`).
- **2026-08-18** — `generic`: `GeoMultiPoint` no longer reuses the `GeoLineString` GraphQL type name (`c318fd4`).

---

*Sources: `docs/APPS.md` § Known Defects & Traps; `docs/components/*.md`; git history.*

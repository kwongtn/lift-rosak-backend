"""Nesting, ordering and ownership for the ``SocialMediaLink`` sublink tree.

WHAT A THREAD IS NOW
--------------------
``SocialMediaLink.parent`` is a self-FK (``tree_queries`` locates the tree by
the field NAME ``parent`` and its CTE hardcodes ``parent_id``), so a thread is
no longer a flat "root row + members hanging off it" group: it is an ordered
nested tree, and a *root* is simply a row with ``parent_id IS NULL``. Nesting
replaces the old depth-1 rule ("``thread`` ALWAYS points at a ROOT") with two
invariants, and both are enforced HERE because no reader should have to
re-derive them:

1. **NO CYCLES** — a link may never become a descendant of itself.
2. **DEPTH <= ``MAX_THREAD_DEPTH``** — see its own section below.

Neither is expressible as a DB CHECK (a cross-row invariant is not a row
constraint), and the library's own loop protection lives in ``TreeNode.clean()``,
which only ever runs under ``full_clean()`` — so ``bulk_update``, and any
``save()`` outside the model guard, are exactly the paths that would break the
first one silently. The model's ``save()`` guard does catch the ``save()`` case
and raises ``ValidationError``; this module owns the *API* contract, which is
``IncidentServiceError`` (a ``ValidationError`` escaping a service reaches the
client as a 500, not as a mutation error), so the refusal happens here, BEFORE
any write. See ``_assert_no_cycle``.

WHY A SILENT CYCLE IS THE WORST OUTCOME AVAILABLE
-------------------------------------------------
A node inside a cycle is not merely hidden: it stays in the table, the recursive
CTE anchors on ``parent_id IS NULL`` and can no longer reach it, so every tree
query returns nothing for it while ``ancestors()`` *on it* raises
``DoesNotExist``. A silently-cycled link is a 500 waiting for whoever next reads
that subtree. There is no repair path in the API — only a hand-written
``UPDATE`` — which is why the check is cheap and eager.

PERMISSION
----------
An admin may group, ungroup and reorder any links. A submitter may operate only
on links they own, checked per link, on the whole selection AND on the named
target parent, and the call is rejected as a unit. A partial write would leave
links nested under a row the caller does not own, with no undo other than
ungrouping them one at a time, so there is no "do what you can" path.

The target is checked on the *named* link, not on the thread root it belongs to.
A submitter who owns a sublink of a thread an admin created can therefore deepen
that shared tree, which is integrity and not confidentiality: no visibility
status changes, nothing is unhidden, and the submitter already sees the rows
they are editing. That trade disappears the moment submitters may nest under a
thread they did not contribute to — then the root has to be checked too.

WHY ``occurred_at`` PICKS THE ROOT
----------------------------------
A thread reads oldest-first, and a thread's root is the row that renders the
card, so the root must be the earliest *event* — not the earliest submission.
``created`` is the wrong column on purpose: a user may backdate a link's
``occurred_at`` to when the disruption actually happened while submitting it
today, and keying the root on ``created`` would render the newest event first
with the old ones stacked under it. ``id`` is only the deterministic tie-break
for links that share an instant — two rows with identical ``occurred_at`` must
not group into a thread whose root depends on insertion order.

Both columns are naive LOCAL datetimes (``USE_TZ = False``,
``TIME_ZONE = "Asia/Kuala_Lumpur"``), so this comparison needs no conversion:
converting one side and not the other would silently shift the ordering by the
UTC offset.

CONCURRENCY
-----------
Every multi-link write is ONE ``transaction.atomic()`` block, so "either every
link moved or none did" is true for grouping, ungrouping and reordering alike.
Every ``select_for_update`` carries a deterministic ``order_by``: an unordered
lock takes its rows in whatever order the planner returns, so two overlapping
calls that then take the same rows in OPPOSITE orders deadlock (Postgres 40P01,
which the client sees as a 500). Deterministic per-query ordering turns that into
"one transaction waits". The ordering is a *per-path* property, not a module-wide
one — ``_group_sync``'s selection is ordered ``occurred_at, id`` because that
ordering IS the root-election rule, while every other lock is ordered ``pk`` — so
cross-path overlap can still deadlock. Each abort is contained by the single
atomic block, so the ceiling is a 500 on a rare concurrent overlap, never a
half-written tree.
"""

from collections.abc import Sequence

from asgiref.sync import sync_to_async
from django.db import transaction

from common.models import User
from incident.models import SocialMediaLink

from .errors import IncidentServiceError

# Write-side cap on ``tree_depth`` (a root is 0), so ``MAX_THREAD_DEPTH = 3``
# admits four levels: root -> sublink -> sub-sublink -> leaf.
#
# WHY A CAP AT ALL: the tree is read by a recursive CTE and shipped as a nested
# selection by the feed query. Both are proportional to how deep real data
# actually goes, and nothing in the product needs an unbounded hierarchy — a
# thread is a handful of links about one disruption, not a filing system. So the
# cap bounds the data the readers have to walk, and 3 leaves room for the
# console's "group under a specific link" without letting an accidental loop of
# manual grouping grow a read nobody bounded.
#
# WHY IT IS A WRITE-SIDE GUARD AND NOT A READ-SIDE ONE: the read side is bounded
# by what the loader actually fetched. A client may select ``sublinks`` nested
# deeper than we store; the levels it asked for and we do not have simply come
# back empty. Clamping on read would invent rows that are not there, so the
# invariant lives where the illegal shape is created.
MAX_THREAD_DEPTH = 3

# The spacing ``tree_queries`` itself uses (``max_sibling_position + 10``). Kept
# identical so a row the library inserts on its own lands in the same series as
# one we renumbered.
_POSITION_STEP = 10

# Postgres cannot lock the nullable side of an outer join, so a
# ``select_for_update`` over a ``select_related`` chain must be narrowed to the
# base table. Nothing here ``select_related``s today, so the clause is a no-op —
# it is kept as the cheapest possible insurance, because the moment someone adds
# a ``select_related`` to the target lookup the error comes back with nothing in
# the diff to explain it.
_LOCK_BASE_TABLE = ("self",)


def _normalize_ids(link_ids: Sequence[int], *, allow_duplicates: bool) -> list[int]:
    """Shape-check the caller's id list. No DB access, so it runs first.

    ``allow_duplicates=False`` for grouping and reordering: the selection comes
    from a rendered list of distinct rows, so a repeated id is a client bug —
    and a silent ``IN`` dedup would hide it while the reindex (which renumbers
    *every* child of the target, not just the named ones) widened the write. For
    reordering a repeat is worse still: the list IS the order, and "which of the
    two mentions goes first" has no answer. Ungrouping is idempotent, so it
    tolerates repeats instead of failing an operator's bulk-clearing click.
    """
    ids = [int(link_id) for link_id in link_ids]
    if not ids:
        raise IncidentServiceError("Select at least one social media link.")
    if not allow_duplicates and len(set(ids)) != len(ids):
        raise IncidentServiceError("The selected social media links repeat an id.")
    # dict.fromkeys: de-duplicate, first-seen order preserved.
    return list(dict.fromkeys(ids))


def _assert_owned(
    user: User, *, is_admin: bool, links: Sequence[SocialMediaLink], label: str
) -> None:
    """Reject the whole call if ANY of ``links`` belongs to somebody else."""
    if is_admin:
        return
    foreign = sorted(link.pk for link in links if link.user_id != user.id)
    if foreign:
        raise IncidentServiceError(
            f"{label} {', '.join(str(pk) for pk in foreign)} is not owned by this user."
        )


def _lock_selected(
    link_ids: Sequence[int], *, order_by: Sequence[str]
) -> list[SocialMediaLink]:
    """Lock the selection, verify it exists, and return it in ``order_by`` order.

    The lock is a *per-query* determinism requirement, not decoration: see the
    CONCURRENCY section. Grouping orders by ``occurred_at, id`` because that
    ordering is the root-election rule; the other paths order by ``pk``, the
    cheapest total order.
    """
    links = list(
        SocialMediaLink.objects.select_for_update()
        .filter(pk__in=link_ids)
        .order_by(*order_by)
    )
    if len(links) != len(link_ids):
        missing = sorted(set(link_ids) - {link.pk for link in links})
        raise IncidentServiceError(
            "Social media link(s) do not exist: "
            f"{', '.join(str(pk) for pk in missing)}."
        )
    return links


def _lock_target(parent_id: int) -> SocialMediaLink:
    """Lock the link a selection is being nested under, or fail cleanly."""
    target = (
        SocialMediaLink.objects.select_for_update(of=_LOCK_BASE_TABLE)
        .filter(pk=parent_id)
        # A ``pk`` lookup returns one row, so its order cannot affect which rows
        # are locked and in what sequence. Stated explicitly anyway: the implicit
        # ``Meta.ordering = ["position"]`` would otherwise be the only lock in
        # the module whose order nobody chose, and a lock-order audit that has to
        # special-case one query is an audit that will eventually miss another.
        .order_by("pk")
        .first()
    )
    if target is None:
        raise IncidentServiceError(f"SocialMediaLink {parent_id} does not exist.")
    return target


def _ancestor_ids(target: SocialMediaLink) -> list[int]:
    """Ids from the tree's ROOT down to ``target`` itself.

    One query answers three questions, which is why it is cached rather than
    recomputed: the target's current depth (it is the last element's index), the
    thread root the caller has to be handed back, and the cycle check below.
    ``include_self=True`` puts the target in the chain, so the degenerate
    "target is one of the selected links" self-loop needs no special case.
    """
    return list(
        SocialMediaLink.objects.ancestors(target, include_self=True)
        .order_by("tree_depth")
        .values_list("pk", flat=True)
    )


def _subtree_height(node: SocialMediaLink) -> int:
    """How many levels the node's own subtree adds below the node (0 = a leaf).

    Counts the descendants that TRAVEL WITH the node, not just the node itself:
    re-parenting a link carries its whole subtree with it, so measuring the node
    alone would let a deep subtree be parked under a shallow target and blow
    straight through ``MAX_THREAD_DEPTH``.

    One query per moved link, inside the caller's single transaction. That is
    deliberate: the alternative — unioning one recursive CTE per link into a
    single statement — is not available, because ``TreeQuerySet`` raises
    ``NotSupportedError`` on ``union()`` (the CTE can only be prepended to a
    whole statement, never inside a compound one). A console selection is a
    handful of rows, so the N queries buy a correct depth check for a price
    nobody can feel.
    """
    depths = list(
        SocialMediaLink.objects.descendants(node, include_self=True)
        # ``position``/``pk`` after ``tree_depth`` so the ordering is total: the
        # library's ``Meta.ordering = ["position"]`` is NOT grouped by parent, and
        # a tie inside one depth level must not decide which end of the range we
        # read.
        .order_by("tree_depth", "position", "pk")
        .values_list("tree_depth", flat=True)
    )
    # ``include_self=True`` guarantees the node is in the set, and it is the only
    # member of its own subtree at its own depth, so first/last bracket the range.
    return depths[-1] - depths[0]


def _assert_no_cycle(
    chain: Sequence[int], movers: Sequence[SocialMediaLink], *, target_pk: int
) -> None:
    """Reject a write that would make a link a descendant of itself.

    ``chain`` is ``_ancestor_ids(target)`` — the target's ancestors, root first,
    target last. The write makes every mover point AT the target, so a cycle
    exists exactly when some mover is already ABOVE the target, i.e. when a mover
    appears in that chain. Asking it this way is the whole point:

    * **Direction.** Walking UP from the single target answers the question for
      the entire selection in one query. The intuitive alternative — "is the
      target a descendant of some mover?" — is the same relation read backwards
      and is the bug the library cannot catch for you: written as
      ``movers[0].descendants()`` it silently only examines the first mover's
      subtree, so a selection of two links where the SECOND one is the target's
      ancestor sails through and writes a cycle. ``chain`` has no such blind
      spot because it does not depend on which mover you happen to test.
    * ``include_self=True`` puts the target in its own chain, so "the target is
      one of the selected links" (a link parented to itself) is the same
      intersection, not a second rule that could drift from the first.
    """
    clashes = sorted({mover.pk for mover in movers} & set(chain))
    if clashes:
        raise IncidentServiceError(
            f"SocialMediaLink {target_pk} cannot take "
            f"{', '.join(str(pk) for pk in clashes)} as sublink(s): it already sits "
            "inside their own subtree, so the hierarchy would become cyclic."
        )


def _assert_depth(
    *, base_depth: int, movers: Sequence[SocialMediaLink], verb: str
) -> None:
    """Reject a write whose deepest result would breach ``MAX_THREAD_DEPTH``.

    ``base_depth`` is the depth the TARGET will occupy *after* the write, so the
    movers land at ``base_depth + 1`` and each carries its own subtree below
    that. Three callers, three answers, one formula:

    * grouping into a NEW thread: the elected root is promoted to depth 0 by this
      very write, so ``base_depth = 0`` — measuring from wherever the root
      happens to sit today would let a promoted deep root smuggle its subtree
      past the cap;
    * grouping under a sublink: ``base_depth`` is that sublink's current depth,
      from ``len(chain) - 1``;
    * reordering the roots: there is no target, so ``base_depth = -1`` and the
      children land at depth 0.

    The bound is on the *resulting* depth, not on the movers' current one, so a
    move that lifts a node out of a deep place is allowed and one that sinks it
    is not.
    """
    deepest = (
        base_depth + 1 + max((_subtree_height(mover) for mover in movers), default=-1)
    )
    if deepest > MAX_THREAD_DEPTH:
        raise IncidentServiceError(
            f"These social media links cannot be {verb} here: the deepest "
            f"resulting level would be {deepest + 1}, past the maximum of "
            f"{MAX_THREAD_DEPTH + 1}."
        )


def _reindex_siblings(
    *,
    parent_id: int | None,
    leading: Sequence[SocialMediaLink],
    dropped: Sequence[int] = (),
) -> list[SocialMediaLink]:
    """Renumber the children of ``parent_id`` and return the rows whose position moved.

    WHY THE SERVICE RENUMBERS AT ALL — the library will not, and getting it
    wrong is user-visible. ``OrderableTreeNode.save()`` assigns
    ``max_sibling_position + 10`` whenever ``position`` is falsy, via a
    read-then-write that is not atomic; that test is ``if not self.position:``
    with no ``_state.adding`` guard, so it is not INSERT-scoped — a row whose
    ``position`` is ``0`` (the column default, which is what a ``bulk_create`` or
    a hand-written ``UPDATE`` leaves behind) has its sibling order rewritten by an
    unrelated later edit. And a RE-PARENT never touches ``position`` at all: the
    moved row keeps whatever number it had under its previous parent, so it can
    land in the middle of the new sibling set and collide with a sibling that
    already holds that number. Two rows sharing a ``position`` make ``ORDER BY
    position`` non-deterministic — the stored sequence is no longer a sequence. So
    every structural write here reindexes the affected set to ``10, 20, 30, …`` in
    the intended order. Determinism beats the library's spacing heuristic for data
    whose order a human reads.

    ``leading`` is the caller's intended order for the rows that are arriving
    here (already sorted by the caller: ``(occurred_at, id)`` when grouping, the
    explicit list order when reordering). Everything else that was already a child
    follows in its stored order, so a regroup puts the freshly nested links
    first without reshuffling the ones that were already there. ``dropped`` names
    rows that are LEAVING this parent; they are excluded from the lock and from
    the renumbering, which is how the vacated slot is closed.
    """
    skip = {row.pk for row in leading} | set(dropped)
    # ``order_by("pk")`` is the deterministic lock order; ``parent_id`` is the
    # filter key, so it is constant across this set and contributes nothing to
    # the ordering. See CONCURRENCY.
    stayers = list(
        SocialMediaLink.objects.select_for_update()
        .filter(parent_id=parent_id)
        .exclude(pk__in=skip)
        .order_by("pk")
    )
    ordered = list(leading) + sorted(stayers, key=lambda row: (row.position, row.pk))
    changed: list[SocialMediaLink] = []
    for index, row in enumerate(ordered, start=1):
        position = index * _POSITION_STEP
        if row.position != position:
            row.position = position
            changed.append(row)
    return changed


def _changed_rows(
    links: Sequence[SocialMediaLink],
    before: dict[int, tuple[int | None, int]],
    reindexed: Sequence[SocialMediaLink],
) -> list[SocialMediaLink]:
    """The rows whose ``parent`` or ``position`` actually moved, de-duplicated.

    ``reindexed`` only covers rows whose POSITION changed, so a link that was
    re-parented while landing on the position it already held would be missing
    from it — the comparison against ``before`` is what puts it back. Diffing is
    also what keeps a repeated identical call a genuine no-op: the old version's
    ``if pending:`` and this are the same discipline, one level down.
    """
    changed: dict[int, SocialMediaLink] = {row.pk: row for row in reindexed}
    for link in links:
        if before[link.pk] != (link.parent_id, link.position):
            changed[link.pk] = link
    return list(changed.values())


def _write_structure(rows: Sequence[SocialMediaLink]) -> None:
    """Persist a structural change: ``parent`` and ``position`` and nothing else.

    ``bulk_update`` writes only the columns it is handed, so ``normalized_url``
    is not recomputed (the model's ``save()`` hook stays bypassed) and
    model_utils' ``modified`` stamp does not move: regrouping is a presentation
    change, not a content edit, and the console's "recently edited" ordering must
    not be reshuffled by it. One statement for the whole group — the surrounding
    atomic block is what makes "either every link moved or none did" true.
    """
    SocialMediaLink.objects.bulk_update(
        list(rows), ["parent", "position"], batch_size=500
    )


def _group_sync(
    user: User, *, is_admin: bool, link_ids: list[int], parent_id: int | None
) -> SocialMediaLink:
    """Resolve, validate and re-parent in ONE transaction. Sync (needs ``atomic``)."""
    with transaction.atomic():
        # ``ORDER BY occurred_at, id`` IS the root-election rule (see the module
        # docstring): the first row is the earliest event, id breaking ties. It
        # doubles as this query's lock order, so determinism is not a second sort
        # key to maintain.
        links = _lock_selected(link_ids, order_by=("occurred_at", "id"))
        _assert_owned(user, is_admin=is_admin, links=links, label="SocialMediaLink")

        # ``promotes_root`` is the new-thread path: the target is the elected root
        # AND it is being lifted out of whatever tree it was in, so it stops
        # pointing anywhere and the cap is measured from depth 0 rather than from
        # where it sits today (a promoted deep root would otherwise smuggle its
        # subtree past the cap).
        promotes_root = parent_id is None
        if promotes_root:
            target = links[0]
            movers = links[1:]
            base_depth: int | None = 0
        else:
            target = _lock_target(parent_id)
            # The target is part of what the caller is editing, so it is
            # permission-checked on the same terms as the selection — a submitter
            # cannot graft their links under somebody else's link. Checked on the
            # NAMED link, not on the thread root, which is the trade recorded in
            # the module docstring.
            _assert_owned(
                user, is_admin=is_admin, links=[target], label="SocialMediaLink"
            )
            movers = links
            base_depth = None  # resolved from the ancestor chain, below

        # ONE query answers the target's depth, the cycle check and the root the
        # caller gets back, so it is fetched once and reused. It is read from the
        # PRE-write state on purpose: the chain is about what the target already
        # is, and nothing on it can move (a mover on the chain is a cycle, which
        # is exactly what the next line rejects).
        chain = _ancestor_ids(target)
        if base_depth is None:
            base_depth = len(chain) - 1
        _assert_no_cycle(chain, movers, target_pk=target.pk)
        _assert_depth(base_depth=base_depth, movers=movers, verb="grouped here")

        # Captured before any mutation, because the lock queries below still see
        # the PRE-write parent in the database (nothing is flushed until the
        # single ``bulk_update`` at the end) and ``_changed_rows`` diffs against
        # exactly this.
        before = {link.pk: (link.parent_id, link.position) for link in links}
        leaving: dict[int, list[int]] = {}
        for link in links:
            old_parent = link.parent_id
            if old_parent is not None and old_parent != target.pk:
                leaving.setdefault(old_parent, []).append(link.pk)

        if promotes_root:
            # Promotion: the elected root stops pointing at whatever it was under,
            # or the group it is being made the root of would hang off a row that
            # is itself inside another thread.
            target.parent_id = None
        for mover in movers:
            # THE POINT OF NESTING: the target is whatever the caller named, root
            # or sublink, and the selection becomes its DIRECT children. The old
            # service resolved a sublink target up to its root and collapsed the
            # group onto it; that flattening is exactly what is being removed, so
            # the root is resolved for the return value only and never imposed on
            # the write.
            mover.parent_id = target.pk

        reindexed = _reindex_siblings(
            parent_id=target.pk,
            leading=sorted(movers, key=lambda row: (row.occurred_at, row.pk)),
        )
        # Close the slot each mover vacated. Without this the old parent's set
        # keeps a hole, and "every sibling set is 10, 20, 30, … with no gaps" —
        # the invariant that makes a later reorder predictable — stops holding.
        for old_parent, pks in leaving.items():
            reindexed.extend(
                _reindex_siblings(parent_id=old_parent, leading=[], dropped=pks)
            )

        rows = _changed_rows(links, before, reindexed)
        if rows:
            _write_structure(rows)
        # ``rows`` empty means the selection already IS this structure: a no-op
        # success, not an error. Re-grouping a live thread is how the UI's
        # "select all" lands, and it must be idempotent.

    # THE ROW THE CALLER GETS BACK, and the two paths differ:
    #
    # * new thread — the elected root IS the thread root, even though the chain
    #   says otherwise. ``chain`` is read from the PRE-write state, and a root
    #   being promoted out of a tree still lists the tree it came from; returning
    #   ``chain[0]`` there would hand back a row the write just detached the
    #   selection from, which is the opposite of useful;
    # * append — the target did not move, so its chain is still valid and
    #   ``chain[0]`` is the thread root. It is stable precisely because a mover
    #   that was an ancestor of the target was rejected as a cycle, so nothing on
    #   the chain moved.
    if promotes_root or len(chain) == 1:
        return target
    return SocialMediaLink.objects.get(pk=chain[0])


async def group_social_media_links(
    user: User,
    *,
    is_admin: bool,
    link_ids: Sequence[int],
    parent_id: int | None = None,
) -> SocialMediaLink:
    """Nest ``link_ids`` under a parent and return the ROOT of the affected thread.

    ``parent_id=None`` STARTS A NEW THREAD: the root is the selected link with
    the smallest ``(occurred_at, id)`` and every other selected link becomes a
    direct child of it, ordered by ``occurred_at`` then ``id``. ``occurred_at``
    rather than ``created`` because the root renders the card and a thread reads
    oldest-first, and a user may have backdated the event while submitting today
    (see the module docstring); ``id`` only breaks ties between links that share
    an instant, because "usually" is not a total order.

    ``parent_id=<a link>`` APPENDS the selection as DIRECT CHILDREN of that
    link, so grouping under a sublink nests one level deeper instead of being
    hoisted to the top — that is the behaviour nesting exists for, and it is why
    this argument is not called a thread id. The target's thread root is
    resolved only to be returned; nothing is collapsed onto it.

    The ROOT is returned rather than the last link written because that is the
    row every thread-scoped reader keys off, so the client can refresh exactly
    it.
    """
    ids = _normalize_ids(link_ids, allow_duplicates=False)
    return await sync_to_async(_group_sync)(
        user, is_admin=is_admin, link_ids=ids, parent_id=parent_id
    )


def _write_structure_parent_only(rows: Sequence[SocialMediaLink]) -> None:
    """Persist a detach: ``parent`` and nothing else. See ``_ungroup_sync``."""
    SocialMediaLink.objects.bulk_update(list(rows), ["parent"], batch_size=500)


def _ungroup_sync(user: User, *, is_admin: bool, link_ids: list[int]) -> None:
    """Clear ``parent`` on exactly these links. Sync (needs ``atomic``)."""
    with transaction.atomic():
        links = _lock_selected(link_ids, order_by=("pk",))
        _assert_owned(user, is_admin=is_admin, links=links, label="SocialMediaLink")
        for link in links:
            link.parent_id = None
        if links:
            # ``["parent"]`` only, deliberately. The promoted links are not
            # renumbered among the roots: this call says "these are no longer
            # nested", not "and they lead the thread in this order", and inventing
            # a root order nobody asked for is a presentation change disguised as
            # a repair. The consequence is honest and small — a promoted link
            # keeps the ``position`` it had under its old parent, so it can tie
            # with a root that already holds that number. Nothing in the codebase
            # orders roots by ``position`` (every feed page is
            # ``occurred_at DESC, id DESC``), and the one surface that does care,
            # the console's root ordering, is ``reorderSocialMediaLinks(
            # parentId: null, …)`` — which renumbers the whole root set and so
            # also clears the tie. Widening the write here would also touch rows
            # the caller never named.
            _write_structure_parent_only(links)


async def ungroup_social_media_links(
    user: User, *, is_admin: bool, link_ids: Sequence[int]
) -> None:
    """Detach exactly ``link_ids``, promoting them to roots.

    DELIBERATELY ASYMMETRIC WITH GROUPING, and both halves are correct — a reader
    will expect a cascade here, so it is worth being explicit about why there is
    not one:

    * ungrouping a link leaves **its own sublinks parented to it**. Only the named
      links are detached. They are not orphaned, not deleted and not re-rooted:
      the branch simply continues under a representative that is now itself a
      root, and ungrouping those sublinks afterwards dissolves it one call at a
      time. A cascade would have to guess a new parent for an arbitrary subtree,
      and every guess is a thread-topology decision the caller did not make;
    * grouping, by contrast, has to RE-POINT rather than clear, because a root
      that merely stopped being a root would leave its new children under a
      ``parent_id IS NULL`` row that is itself somebody's sublink's sibling —
      i.e. two threads in one.

    A user who wants the whole branch dissolved ungroups from the top down; the
    UI's "ungroup this thread" does exactly that, and each intermediate state is
    a legal tree.
    """
    ids = _normalize_ids(link_ids, allow_duplicates=True)
    await sync_to_async(_ungroup_sync)(user, is_admin=is_admin, link_ids=ids)


def _reorder_sync(
    user: User, *, is_admin: bool, parent_id: int | None, link_ids: list[int]
) -> None:
    """Set one sibling sequence explicitly. Sync (needs ``atomic``)."""
    with transaction.atomic():
        # ``order_by("pk")``: the incoming ``link_ids`` order is the ORDER being
        # written, not the lock order, and locking in the caller's order would
        # make two concurrent reorders of overlapping sets deadlock. The lock
        # order has to be a function of the rows alone.
        links = _lock_selected(link_ids, order_by=("pk",))
        _assert_owned(user, is_admin=is_admin, links=links, label="SocialMediaLink")

        # Sibling membership FIRST: it is the cheapest and most specific
        # rejection, and a link that is not a child of the named parent can never
        # be the target's ancestor either, so checking it first means the cycle
        # message is never shown for what is really a "wrong set" mistake.
        foreign = sorted(link.pk for link in links if link.parent_id != parent_id)
        if foreign:
            raise IncidentServiceError(
                "reorderSocialMediaLinks permutes one set of siblings: "
                f"SocialMediaLink {', '.join(str(pk) for pk in foreign)} is not a "
                "sublink of the named parent. Use groupSocialMediaLinks to move a "
                "link to a different parent."
            )

        if parent_id is None:
            # ``parent_id = None`` means "reorder the ROOTS", and it is a real
            # use, not a degenerate one: the console wants to control which link
            # leads a thread. There is no target, so there is nothing to close a
            # cycle through, and the children land at depth 0.
            base_depth = -1
        else:
            target = _lock_target(parent_id)
            _assert_owned(
                user, is_admin=is_admin, links=[target], label="SocialMediaLink"
            )
            chain = _ancestor_ids(target)
            # Unreachable through this mutation's own sibling precondition — a
            # mover is a child of the target, and a node that is both a child and
            # an ancestor of the same node is the target itself. Kept because the
            # alternative is not "silently wrong", it is a 500: on hand-edited data
            # that already contains a cycle, ``_ancestor_ids`` raises
            # ``DoesNotExist`` rather than returning a chain, and the service
            # should own that failure instead of leaking it.
            _assert_no_cycle(chain, links, target_pk=target.pk)
            base_depth = len(chain) - 1

        _assert_depth(base_depth=base_depth, movers=links, verb="reordered here")

        # The order the CALLER sent is the order being written, so the rank map is
        # built from ``link_ids`` — not from ``links``, which is the selection in
        # ``pk`` order because that is the lock order. Reading the rank off the
        # locked rows would silently make reorder a no-op whenever the caller's
        # order differs from the primary-key order, which is every interesting
        # case.
        rank_of = {link_id: index for index, link_id in enumerate(link_ids)}
        before = {link.pk: (link.parent_id, link.position) for link in links}
        for link in links:
            link.parent_id = parent_id

        reindexed = _reindex_siblings(
            parent_id=parent_id, leading=sorted(links, key=lambda r: rank_of[r.pk])
        )
        rows = _changed_rows(links, before, reindexed)
        if rows:
            _write_structure(rows)


async def reorder_social_media_links(
    user: User,
    *,
    is_admin: bool,
    parent_id: int | None,
    link_ids: Sequence[int],
) -> None:
    """Make ``link_ids`` the children of ``parent_id``, in exactly that order.

    WHY THIS EXISTS: ``position`` is a stored, user-visible sequence — the
    console's move-up/move-down and the nested feed selection both read it — and
    nothing else in the API can set it. ``groupSocialMediaLinks`` only ever
    appends a selection in ``occurred_at`` order and ``reorder``-less grouping
    would leave that order as the sole authority, so the console could not put a
    link first. A stored sequence nobody can set is not a feature.

    It is a PERMUTATION of one sibling set, not a move: every id must already be
    a child of ``parent_id`` (a child of ``None`` when ``parent_id is None``).
    Anything else is rejected rather than quietly re-parented, because a reorder
    that also regroups is a ``groupSocialMediaLinks`` with extra steps and a
    much worse failure mode. The named order becomes positions ``10, 20, 30, …``
    and any sibling not named keeps its relative order after them.

    ``parent_id=None`` reorders the roots. The same cycle and depth rules apply —
    with no target there is no cycle to close, and re-parenting to the root level
    can only ever make a link shallower.
    """
    ids = _normalize_ids(link_ids, allow_duplicates=False)
    await sync_to_async(_reorder_sync)(
        user, is_admin=is_admin, parent_id=parent_id, link_ids=ids
    )

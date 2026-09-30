"""Thread grouping for ``SocialMediaLink``: who may group, and what a thread IS.

THE INVARIANT (the reason this module exists rather than a set of ad-hoc UPDATEs)
--------------------------------------------------------------------------------
``SocialMediaLink.thread`` is a self-FK and a thread is represented by its ROOT
row: the root has ``thread_id IS NULL`` and *is* the thread; every other member
carries ``thread = <root>``. The rule this module exists to keep true is:

    ``thread`` ALWAYS points at a ROOT — i.e. ``link.thread.thread_id is None``.

Which means depth is exactly 1 and there are no cycles. Every other surface
depends on that and is allowed to assume it without re-deriving it:

* the scalar field resolvers answer ``isThreadRoot`` with ``thread_id is None``
  and size a thread as ``root.thread_members`` + 1, with no second hop;
* the collapsed public feed filters ``thread__isnull=True`` and treats the
  surviving row as the whole group;
* a batch loader keyed by root id can never be handed a member's id and cannot
  return a nested structure.

There is no DB-level check constraint for it (a cross-row invariant is not
expressible as a row CHECK), so the enforcement is entirely here: a group write
is ONE ``transaction.atomic()`` block that resolves the target root, re-points
the selection at it, and FLATTENS any pre-existing members of the selected roots
onto that same root. Drop the flatten step and merging two existing threads
silently produces depth 2, which every one of those surfaces then mis-reads.

PERMISSION
----------
An admin may group any links. A logged-in submitter may group ONLY their own —
checked per link, on the whole selection AND on the target thread, and the call
is rejected as a unit. A partial group would leave links threaded to a root the
caller does not own, which is a leak with no undo other than ungrouping one
link at a time, so there is no "do what you can" path.

The check is deliberately applied to the *named* target, not to the root
``_resolve_root`` derives from it — a submitter can therefore append to a
cross-owner thread's root. That is an integrity trade, not a disclosure, and the
reasoning plus the invariant it depends on ("only an admin can create a
cross-owner thread") is recorded at the call site in ``_group_sync``, which is
where a future change to the permission rules has to be noticed.

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
"""

from collections.abc import Sequence

from asgiref.sync import sync_to_async
from django.db import transaction

from common.models import User
from incident.models import SocialMediaLink

from .errors import IncidentServiceError

# Postgres cannot lock the nullable side of an outer join, so a
# ``select_for_update`` over a ``select_related`` chain must be narrowed to the
# base table. Also the reason the target lookup can join two hops without
# risking "FOR UPDATE cannot be applied to the nullable side of an outer join".
_LOCK_BASE_TABLE = ("self",)


def _normalize_ids(link_ids: Sequence[int], *, allow_duplicates: bool) -> list[int]:
    """Shape-check the caller's id list. No DB access, so it runs first.

    ``allow_duplicates=False`` for grouping: the selection comes from a rendered
    list of distinct rows, so a repeated id is a client bug — and a silent
    ``IN`` dedup would hide it while the flatten step (which re-points
    *everything* hanging off a selected link) widened the write. Ungrouping is
    idempotent, so it tolerates repeats instead of failing an operator's
    bulk-clearing click over it.
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


def _resolve_root(target: SocialMediaLink) -> SocialMediaLink:
    """Follow ``thread`` until it lands on a ROOT row.

    Under the invariant this is a single hop, and the two ``select_related``
    levels on the target lookup cover it without a second query. The loop is a
    cheap guard, not a design element: if a row somehow points at a member
    (hand-edited data, a future write path that forgets to flatten), the group
    still lands on a real root instead of deepening the graph. ``seen`` turns a
    pre-existing cycle into a clean error rather than an infinite query loop.
    """
    seen = {target.pk}
    current = target
    while current.thread_id is not None:
        if current.thread_id in seen:
            raise IncidentServiceError(
                f"SocialMediaLink {current.pk} is part of a thread cycle; "
                "the grouping must be repaired before it can be extended."
            )
        seen.add(current.thread_id)
        current = current.thread
    return current


def _group_sync(
    user: User, *, is_admin: bool, link_ids: list[int], thread_id: int | None
) -> SocialMediaLink:
    """Resolve + re-point in a single transaction. Sync (needs ``atomic``)."""
    selected_ids = list(link_ids)

    with transaction.atomic():
        # ``ORDER BY occurred_at, id`` IS the root rule (see the module
        # docstring): the first row is the earliest event, id breaking ties.
        links = list(
            SocialMediaLink.objects.select_for_update()
            .filter(pk__in=selected_ids)
            .order_by("occurred_at", "id")
        )
        if len(links) != len(selected_ids):
            missing = sorted(set(selected_ids) - {link.pk for link in links})
            raise IncidentServiceError(
                "Social media link(s) do not exist: "
                f"{', '.join(str(pk) for pk in missing)}."
            )
        _assert_owned(user, is_admin=is_admin, links=links, label="SocialMediaLink")

        if thread_id is None:
            root = links[0]
        else:
            target = (
                SocialMediaLink.objects.select_for_update(of=_LOCK_BASE_TABLE)
                .select_related("thread", "thread__thread")
                .filter(pk=thread_id)
                .first()
            )
            if target is None:
                raise IncidentServiceError(
                    f"SocialMediaLink {thread_id} does not exist."
                )
            # The target thread is part of what the caller is editing, so it
            # is permission-checked on the same terms as the selection — a
            # submitter cannot graft their links onto somebody else's thread.
            _assert_owned(
                user, is_admin=is_admin, links=[target], label="SocialMediaLink"
            )
            # Appending to a MEMBER must resolve to the member's real root, or
            # the group would nest (member -> member) and break the invariant
            # that every scalar field resolver and loader is allowed to assume.
            #
            # WHY THE RESOLVED ROOT IS NOT RE-CHECKED AGAINST ``_assert_owned``
            # ----------------------------------------------------------------
            # It looks like a gap: a submitter who names THEIR OWN member of a
            # cross-owner thread resolves to a root they do not own and appends
            # to it. It is not a leak, and the reasoning is worth keeping — but
            # it rests on an invariant, so read the invariant, not the
            # conclusion:
            #
            #   **only an admin can create a cross-owner thread.** A submitter's
            #   selection and the named target are both checked to be theirs, so
            #   the reachable set of foreign roots is exactly the roots that
            #   already contain a link the caller owns. The caller is therefore
            #   already a member of the thread they are appending to — they see
            #   the root and every publicly-visible member of it on the collapsed
            #   public feed (the same rendering the mutation perturbs), and their
            #   own row is on their own ``mine`` list. Nothing becomes readable
            #   that was not already readable.
            #
            # What the gap DOES permit is a write to a shared object: the caller
            # can add their own links to a thread they do not control, and — via
            # the flatten step below, whose ``absorbed`` set is keyed on the
            # selection they own — can relocate the members of their own link
            # onto that foreign root. Both are integrity, not confidentiality:
            # no visibility status is changed, nothing is unhidden, and a member
            # moved between two roots was a member of both.
            #
            # The whole argument evaporates if the permission rules change — e.g.
            # if submitters ever become able to group onto a named thread they
            # did not contribute to, or if a non-admin path is added that writes
            # ``thread`` directly. Re-check the root the moment either happens;
            # a second ``_assert_owned(root)`` here is the whole fix, and the
            # error message it would raise would need to distinguish "the link
            # you named is not yours" from "the ROOT of that thread is not
            # yours", because they are different mistakes with different fixes.
            root = _resolve_root(target)

        # A link can never point at itself; the root keeps ``thread_id = None``.
        pending: dict[int, SocialMediaLink] = {}
        if root.thread_id is not None:
            # Only reachable on the ``thread_id is None`` path: the selected root
            # is currently a member of some other thread and is being promoted.
            # That other thread keeps its own un-selected members; depth stays 1
            # because this row stops pointing anywhere.
            pending[root.pk] = root
            root.thread_id = None

        for link in links:
            if link.pk == root.pk:
                continue
            link.thread_id = root.pk
            pending[link.pk] = link

        # FLATTEN. Anything already hanging off a selected link follows it to
        # the new root in the same statement — otherwise merging two live
        # threads would leave the old members one level deeper than every
        # reader expects. Under the invariant the selected links' only members
        # are the ones belonging to the selected ROOTS, so this is exactly
        # "re-point the absorbed threads' members", and it is a no-op (same
        # value) for a link that already points at the new root.
        #
        # ``order_by("pk")`` is LOAD-BEARING, not tidiness. ``select_for_update``
        # locks rows in the order the planner hands them back, and without an
        # ORDER BY that order is whatever the access path produced — for an
        # ``IN`` list over a small table, effectively the physical/scan order.
        # Two overlapping groupings that then take the same rows in opposite
        # orders deadlock (Postgres detects the cycle, aborts one with 40P01, and
        # the client sees a 500). A deterministic lock order is what makes
        # concurrent groupings safe: every caller asks for the same rows in the
        # same sequence, so one transaction waits instead of forming a cycle.
        # ``pk`` is the cheapest total order, and ``thread_id`` carries none here
        # — it is the filter key, so it is constant across the locked set.
        #
        # RESIDUAL, stated so nobody reads the line above as a blanket safety
        # claim: the ordering is a *per-path* property, not a module-wide one.
        # The selection query in this function is ordered ``occurred_at, id``
        # because that ordering IS the root-election rule and must not change;
        # ``_ungroup_sync`` orders its own lock by ``pk``. So a grouping and an
        # ungrouping that overlap on the same rows still lock in two different
        # orders and can still deadlock. Every such abort is contained by the
        # single ``transaction.atomic()`` around each of them, so the ceiling is
        # a 500 on a rare concurrent overlap, never a half-written thread.
        absorbed = (
            SocialMediaLink.objects.select_for_update()
            .filter(thread_id__in=selected_ids)
            # ``pk`` not ``(thread_id, pk)``: ``thread_id`` IS the filter key
            # here, so it is constant across the locked set and contributes
            # nothing to the order.
            .order_by("pk")
        )
        for member in absorbed.exclude(pk=root.pk):
            if pending.get(member.pk) is not None:
                continue
            member.thread_id = root.pk
            pending[member.pk] = member

        if pending:
            # ``bulk_update`` writes only the columns it is given, so
            # ``normalized_url`` is not recomputed (the model's ``save()`` hook
            # stays bypassed) and model_utils' ``modified`` stamp does not move:
            # regrouping is a presentation change, not a content edit, and the
            # console's "recently edited" ordering must not be reshuffled by it.
            # One statement for the whole group — the surrounding atomic block
            # is what makes "either every link moved or none did" true.
            SocialMediaLink.objects.bulk_update(
                list(pending.values()), ["thread"], batch_size=500
            )
        # ``pending`` empty means the selection already is one thread: a no-op
        # success, not an error. Re-grouping a live thread is how the UI's
        # "select all" lands, and it must be idempotent.

    return root


async def group_social_media_links(
    user: User,
    *,
    is_admin: bool,
    link_ids: Sequence[int],
    thread_id: int | None = None,
) -> SocialMediaLink:
    """Group ``link_ids`` into one thread and return its ROOT row.

    ``thread_id=None`` roots the group at the selection's earliest
    ``(occurred_at, id)``; ``thread_id=<a link>`` appends to that link's
    existing thread (resolving a member up to its root first). The root is
    returned — not the last link written — because that is the row every
    thread-scoped reader keys off, so the caller can refresh exactly it.
    """
    ids = _normalize_ids(link_ids, allow_duplicates=False)
    return await sync_to_async(_group_sync)(
        user, is_admin=is_admin, link_ids=ids, thread_id=thread_id
    )


def _ungroup_sync(user: User, *, is_admin: bool, link_ids: list[int]) -> None:
    """Clear ``thread`` on exactly these links. Sync (needs ``atomic``)."""
    with transaction.atomic():
        # ``order_by("pk")`` for the same reason as the ``absorbed`` query in
        # ``_group_sync``: an unordered ``select_for_update`` takes its locks in
        # whatever order the planner returns, so two ungroupings over overlapping
        # selections (two operators bulk-clearing the same console page) can lock
        # the same rows in opposite orders and deadlock. The two ops are then
        # forced to disagree — the grouping path's selection is ordered
        # ``occurred_at, id`` because that ordering is the root rule — so
        # cross-path overlap can still deadlock; the atomic block is what keeps
        # that abort to a 500 rather than a partial ungroup.
        links = list(
            SocialMediaLink.objects.select_for_update()
            .filter(pk__in=link_ids)
            .order_by("pk")
        )
        if len(links) != len(link_ids):
            missing = sorted(set(link_ids) - {link.pk for link in links})
            raise IncidentServiceError(
                "Social media link(s) do not exist: "
                f"{', '.join(str(pk) for pk in missing)}."
            )
        _assert_owned(user, is_admin=is_admin, links=links, label="SocialMediaLink")
        for link in links:
            link.thread_id = None
        if links:
            SocialMediaLink.objects.bulk_update(links, ["thread"], batch_size=500)


async def ungroup_social_media_links(
    user: User, *, is_admin: bool, link_ids: Sequence[int]
) -> None:
    """Detach exactly ``link_ids`` from their threads.

    Deliberately ASYMMETRIC with grouping, and both halves are correct:

    * ungrouping a ROOT leaves its members attached — they were never named, and
      the root row is the only thing that changed. The thread is still a thread
      with a new representative;
    * ungrouping MEMBERS one at a time eventually leaves the original root a
      singleton, which is the intended "dissolve" path: no cascade, no re-root
      election, and every intermediate state is a legal depth-1 graph.

    Doing the same thing to grouping would be wrong in the other direction: a
    root has to be re-pointed, not cleared, or the members would dangle.
    """
    ids = _normalize_ids(link_ids, allow_duplicates=True)
    await sync_to_async(_ungroup_sync)(user, is_admin=is_admin, link_ids=ids)

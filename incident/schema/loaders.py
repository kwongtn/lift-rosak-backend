from collections import defaultdict

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Sum
from strawberry.dataloader import DataLoader

from common.models import Vote
from incident.models import CalendarIncident, CalendarIncidentMedia, SocialMediaLink


async def batch_load_medias_from_calendar_incident(keys):
    incident_medias = CalendarIncidentMedia.objects.filter(
        calendar_incident_id__in=keys,
    ).select_related("media")

    incident_dict = defaultdict(set)
    async for incident_media in incident_medias:
        incident_dict[incident_media.calendar_incident_id].add(incident_media.media)

    return [incident_dict.get(key, set()) for key in keys]


async def batch_load_vote_scores(keys):
    """
    Batch load net vote scores (sum of vote values).
    Keys: list of (content_type_id, object_id) tuples
    Returns: list of integers (net scores aligned to keys)
    """
    content_type_ids = [k[0] for k in keys]
    object_ids = [k[1] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        )
        .values("content_type_id", "object_id")
        .annotate(score=Sum("value"))
    )

    scores = {(v["content_type_id"], v["object_id"]): v["score"] or 0 for v in votes}
    return [scores.get(k, 0) for k in keys]


async def batch_load_vote_breakdown(keys):
    """
    Batch load vote breakdown (upvote/downvote counts).
    Keys: list of (content_type_id, object_id) tuples
    Returns: list of dict {"upvotes": int, "downvotes": int}
    """
    content_type_ids = [k[0] for k in keys]
    object_ids = [k[1] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        )
        .values("content_type_id", "object_id", "value")
        .annotate(count=Count("id"))
    )

    breakdown = defaultdict(lambda: {"upvotes": 0, "downvotes": 0})
    for v in votes:
        key = (v["content_type_id"], v["object_id"])
        if v["value"] == 1:
            breakdown[key]["upvotes"] = v["count"]
        elif v["value"] == -1:
            breakdown[key]["downvotes"] = v["count"]

    return [breakdown[k] for k in keys]


async def batch_load_user_vote_value(keys):
    """
    Batch load current user's vote value for objects.
    Keys: list of (user_id, content_type_id, object_id) tuples
    Returns: list of int (-1, 0, 1) aligned to keys
    """
    user_ids = [k[0] for k in keys]
    content_type_ids = [k[1] for k in keys]
    object_ids = [k[2] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            user_id__in=user_ids,
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        ).values("user_id", "content_type_id", "object_id", "value")
    )

    vote_map = {
        (v["user_id"], v["content_type_id"], v["object_id"]): v["value"] for v in votes
    }
    return [vote_map.get(k, 0) for k in keys]


async def batch_load_incident_links(keys):
    """
    Batch load SocialMediaLink rows for the incident cards' link lists (page one).

    Keys: list of ``(incident_id, first)`` tuples — the nested
    ``CalendarIncidentScalar.links`` field, when called without ``after``, loads
    through this loader, so a feed of N cards issues ONE row query instead of
    N+1 (repo rule: resolvers that fan out to related rows must use a loader).

    Continuation pages (``after`` present) are NOT loadable this way: each parent
    carries its own per-parent keyset cursor, so per-parent windows cannot be
    batched into one shared query — the field queries those individually
    (documented in the field's docstring).

    Returns: list of lists of SocialMediaLink, aligned to keys, each sliced to
    ``first + 1`` rows (the extra row lets the field compute has_next_page
    without a separate count query). The lazy iterator stops as soon as every
    incident has its window, so the fetch stays bounded to the largest requested
    first-page size rather than pulling every link of every batched incident.
    """
    incident_ids = [key[0] for key in keys]
    max_first = max(key[1] for key in keys)

    content_type = await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncident
    )

    # ``-occurred_at, -id`` (NOT ``-created``): every other link list in the
    # schema orders on the event instant, and this one has to match so a nested
    # card list and a feed page cannot disagree about which link is "newest" —
    # an incident whose newest submission was about last Tuesday must not sort
    # its newest-event link below a fresher report. The ``(occurred_at, id)``
    # pair is also what the keyset cursor encodes, so ordering here and the
    # cursor in ``CalendarIncidentScalar.links`` cannot drift apart.
    links = SocialMediaLink.objects.filter(
        content_type=content_type,
        object_id__in=incident_ids,
    ).order_by("-occurred_at", "-id")

    target = max_first + 1
    by_incident = defaultdict(list)
    async for link in links:
        by_incident[link.object_id].append(link)
        if len(by_incident) == len(incident_ids) and all(
            len(rows) >= target for rows in by_incident.values()
        ):
            break

    return [by_incident.get(key[0], [])[: key[1] + 1] for key in keys]


def _sibling_groups(
    rows: list[SocialMediaLink],
) -> dict[int | None, list[SocialMediaLink]]:
    """Bucket a flat subtree by ``parent_id``, each bucket in ``position`` order.

    ``position`` is the sibling sequence (``reorderSocialMediaLinks`` writes it),
    but ``Meta.ordering = ["position"]`` is GLOBAL: every level of the tree
    numbers its children from the same base, so a child of a child can hold the
    same ``position`` as its own parent (M1 pins this in
    ``tests/incident/test_social_link_tree_model.py``). Sorting the flat list
    therefore cannot express "these two are siblings" — the bucketing has to
    happen on ``parent_id`` first, and only then does ``position`` mean anything.
    ``id`` breaks ties so the order is total, matching every other ordering in
    the schema (``occurred_at DESC, id DESC`` and friends).
    """
    groups: dict[int | None, list[SocialMediaLink]] = defaultdict(list)
    for row in rows:
        groups[row.parent_id].append(row)
    for group in groups.values():
        group.sort(key=lambda row: (row.position, row.pk))
    return groups


def _depth_first(rows: list[SocialMediaLink], root_id: int) -> list[SocialMediaLink]:
    """Re-order a flat subtree into depth-first order, siblings by ``position``.

    This is what makes the loader's FLAT answer usable as a tree: a field that
    wants its direct children filters ``parent_id == self.id`` out of the result
    and the order it needs is already there, so no field has to sort and no
    field can sort it differently from its sibling.
    """
    groups = _sibling_groups(rows)
    ordered: list[SocialMediaLink] = []
    stack = list(reversed(groups.get(root_id, [])))
    while stack:
        row = stack.pop()
        ordered.append(row)
        stack.extend(reversed(groups.get(row.pk, [])))
    return ordered


async def batch_load_sublink_subtrees(
    keys: list[int],
) -> list[list[SocialMediaLink]]:
    """
    Batch load each requested link's whole subtree, at any depth.

    Keys: list of ``SocialMediaLink`` ids (``int``) — ``SocialMediaLinkScalar
    .sublinks`` / ``.sublinkCount``. Callers pass ``self.id`` unconditionally
    rather than branching on root-ness first: a link with nothing under it simply
    has no subtree, so it comes back empty. Working that out per row would cost
    a second round trip (does this id have children?) to learn something the
    answer already implies.

    Returns: list of lists of SocialMediaLink, aligned POSITIONALLY to ``keys``,
    duplicate keys included — that is the DataLoader contract, and a resolver
    that indexes the answer by position must not get somebody else's list. Each
    list is FLAT (no nesting is built here, only the ORDER of a nesting: depth
    first, siblings in ``position`` order) and holds the node's descendants at
    every depth, never the node itself. Every key gets a list back, empty for a
    childless link, never a missing key, hence the ``.get`` in the return.

    ONE QUERY PER SUBTREE, NOT ONE PER LEVEL — the reason this loader exists and
    the reason it is shaped this way. ``node.children`` is a plain
    ``RelatedManager``, so walking the tree in Python the obvious way costs one
    query per LEVEL per node: a depth-3 tree resolved field-by-field is 3
    queries for the same answer one ``descendants()`` CTE gives in 1. Fetching
    the whole subtree once and rebuilding the nesting in Python (``_depth_first``)
    removes that entirely, and as a bonus makes ``sublinkCount`` and ``sublinks``
    structurally incapable of disagreeing — they are two reads of one fetched
    list, so there is no second count that could drift from the list it labels.
    The loader is deep-copied per request (``rosak/context.py``), so within one
    request a key is fetched once and BOTH fields cost that single query.

    One query for the whole batch, then one per threaded key:

    1. ``filter(parent_id__in=keys).values_list("parent_id", flat=True)`` — one
       indexed FK lookup for the WHOLE batch, no CTE, answering "which of these
       ids have any child at all?". Keys that come back absent are answered
       ``[]`` without a second query, which is the common case: most links on a
       feed page hang off nothing.
    2. one ``descendants(include_self=False)`` per key that survived step 1 — a
       single recursive-CTE statement each, filtered by nothing (see the
       visibility note below). A page of N rows therefore costs
       ``1 + (number of rows that have children)`` queries, NOT ``N`` and NOT
       ``N * depth``.

    Deliberately NOT filtered for public visibility here: this loader is the
    data layer, and the moderation rule lives in exactly one place
    (``incident.services.social_link_visibility.is_publicly_visible``).
    Duplicating it as a queryset ``.exclude()`` is how two copies drift, and the
    copy that drifts is the one that leaks a hidden row's URL into a public feed
    through a nested field. The scalar fields filter the returned rows with the
    shared predicate instead — same rows, one rule — and they do it from THIS
    one fetch, so the badge and the list stay in step.

    No ``tree_filter``/``tree_exclude`` either: those restrict the base table
    before the CTE, and the only predicate this query needs is "every descendant
    of this node", which the ``tree_path`` containment already expresses. A tree
    filter would help only if the base table were large enough that the CTE's
    anchor scan dominates — and the obvious candidate (hide the moderation rows)
    is exactly the rule that must not be duplicated here.
    """
    # Dedupe for the QUERIES only. The answer is still assembled from ``keys``,
    # so a repeated key is answered at its own position.
    wanted = set(keys)

    # Step 1 — the cheap existence probe, one query for the whole batch. A plain
    # indexed FK lookup: no recursive CTE, and it is the only place a childless
    # key is answered, which is what keeps step 2 off the common path.
    populated = await sync_to_async(set)(
        SocialMediaLink.objects.filter(parent_id__in=wanted).values_list(
            "parent_id", flat=True
        )
    )

    by_key: dict[int, list[SocialMediaLink]] = {key: [] for key in wanted - populated}

    # Step 2 — one whole-subtree fetch per key that actually has children.
    # ``.order_by()`` clears ``Meta.ordering``: the ordering that matters is
    # per-sibling, and it cannot be expressed in SQL for a multi-level fetch
    # anyway (see ``_sibling_groups``), so the sort happens in Python where it is
    # per-parent by construction. Sorting in SQL would also make the answer
    # depend on a global default that only means something at one level.
    for key in sorted(populated):
        rows = [
            row async for row in SocialMediaLink.objects.descendants(key).order_by()
        ]
        by_key[key] = _depth_first(rows, key)

    return [by_key.get(key, []) for key in keys]


IncidentContextLoaders = {
    "medias_from_calendar_incident_loader": DataLoader(
        load_fn=batch_load_medias_from_calendar_incident
    ),
    "vote_scores": DataLoader(batch_load_vote_scores),
    "vote_breakdown": DataLoader(batch_load_vote_breakdown),
    "user_vote_value": DataLoader(batch_load_user_vote_value),
    "incident_links": DataLoader(batch_load_incident_links),
    "sublink_subtrees": DataLoader(batch_load_sublink_subtrees),
}

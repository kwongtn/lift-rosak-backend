"""Single source of truth for "may this link be shown to the public?".

``get_public_social_media_links`` inlines the two exclusion gates below, and
the threaded card needs the same answer per *member* link (``threadLinks`` /
``threadSize`` count what a visitor would actually be able to open, not what is
merely attached to the root). Two copies of a moderation rule is how a public
feed ends up leaking hidden rows through a thread badge, so the rule lives here
and every surface imports it.

Imported by name as
``from incident.services.social_link_visibility import is_publicly_visible`` —
this module is deliberately *not* re-exported from ``incident.services`` so a
modest addition cannot drag the whole service package into a scalar field's
import graph.
"""

from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink


def is_publicly_visible(link: SocialMediaLink) -> bool:
    """Not HIDDEN, and not an unapproved automated capture.

    HIDDEN is ABSOLUTE: it is a moderation decision, so it beats any explicit
    status narrowing and the caller must apply this predicate *after* narrowing
    by status. ``status: HIDDEN`` must return an empty page, not resurrect what
    the decision removed.

    ``mine`` IS an exception to the gates — but NOT to this predicate, and the
    split is deliberate:

    * ``get_public_social_media_links`` skips the *queryset-level* ``.exclude()``
      pair under ``mine``, so an owner still sees their own HIDDEN and
      unapproved-automated rows on "My Submitted Links";
    * this *per-row* predicate is applied unconditionally — by the scalar's
      ``threadLinks`` / ``threadSize`` on every surface, ``mine`` included.

    So a hidden member is not listed inside a thread on the ``mine`` page either.
    The coherence argument: the owner's own list is a list of *their
    submissions*, and the root row carrying the decision is one of them — a
    submitter must still be able to see the thing an admin hid in order to ask
    about it. A thread's member list is not that: it is a *rendering of a shared
    object*, the same nesting a public visitor sees, so honouring the caller's
    ownership there would publish through a personal page exactly what
    moderation removed from every other surface. Owning a member is not owning
    the thread.

    The approval gate is scoped to ``is_automated`` on purpose: an official post
    that ingestion inserted but nobody has approved is not public, whereas a
    *community* link awaiting approval keeps today's behaviour and still
    surfaces with its pending pill. Hiding pending rows wholesale would silently
    hide hand-submitted reports too, which is the opposite of what a moderation
    queue is for.

    This mirrors the queryset-level ``.exclude(...)`` pair in the public feed
    resolver — it is a per-row predicate, so it does not replace those; it
    exists so non-queryset code (scalar field resolvers, Python-side filtering
    over loader results) cannot drift from them. The one place the two
    deliberately disagree is ``mine``, as above: a rule that holds "except on
    the personal list" is only coherent if the exemption is written down, and
    this is where it is written down.
    """
    if link.status == SocialMediaLinkStatus.HIDDEN:
        return False
    return not (
        link.is_automated and link.status == SocialMediaLinkStatus.PENDING_APPROVAL
    )

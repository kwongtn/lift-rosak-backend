"""Backfill: approved-but-pending official posts become LIVE.

Official-post ingestion now creates rows ``LIVE`` (auto-published by policy), so
no admin action sits between the operator's announcement and the public feed.
Rows ingested under the old policy are still sitting in ``PENDING_APPROVAL`` —
and, because re-ingest skips an existing ``(socmed_account, post_id)`` /
``normalized_url`` row, nothing will ever move them. This data-only migration
flips exactly those rows once.

WHAT MOVES, AND WHAT DOES NOT
-----------------------------
Only ``is_automated=True AND status="pending_approval"``. A ``HIDDEN`` row is a
moderation decision, not a lifecycle stage (see ``SocialMediaLinkStatus``), so it
is never touched by the backfill — a hidden official post stays hidden. Community
links are out of scope by the ``is_automated`` filter: they keep their pending
state and their existing public visibility, unchanged.

RAW STRINGS, DELIBERATELY
-------------------------
``apps.get_model`` returns a HISTORICAL model whose field is whatever the state
at migration 0031 declared. Values are therefore spelled as the raw stored
strings ("pending_approval" / "live") rather than importing
``incident.enums.SocialMediaLinkStatus``: an enum member renamed later must not
retroactively change what this migration writes, and the persisted values are
exactly those lowercase strings (``TextChoicesField``).

NO MODEL CHANGE
---------------
This is a pure data pass — ``operations`` carries a single ``RunPython``, so
``makemigrations --check`` stays clean.
"""

from django.db import migrations


def approve_pending_official_links(apps, schema_editor):
    """One-UPDATE backfill, keyed on the two columns that define the policy gap."""
    SocialMediaLink = apps.get_model("incident", "SocialMediaLink")
    # One statement, no Python-side loop: the predicate and the update are read
    # and written in the same query, so nothing can reinterpret a value between.
    SocialMediaLink.objects.filter(
        is_automated=True,
        status="pending_approval",
    ).update(status="live")


class Migration(migrations.Migration):
    dependencies = [
        ("incident", "0031_socialmedialink_tree_parent_and_more"),
    ]

    operations = [
        # Irreversible on purpose: a reverse that re-pended every LIVE automated
        # row would resurrect the old approval policy and hide official posts
        # that were already published. WHICH rows this flipped is not knowable
        # afterwards — the forward update leaves no marker — so re-pending them
        # would be a guess with a public-feed consequence, not an undo.
        migrations.RunPython(
            approve_pending_official_links,
            migrations.RunPython.noop,
        ),
    ]

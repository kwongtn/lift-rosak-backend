"""``SocialMediaLink``: flat one-level ``thread`` → ordered nested tree.

``django-tree-queries`` stores NOTHING. ``tree_path`` is a recursive-CTE
annotation recomputed per query, so the whole shape change is "two columns plus
a data pass" — no redundant path column, no in-memory tree, no signal on every
save. On top of ``TimeStampedModel`` the model now also inherits
``OrderableTreeNode``, which contributes ``position``
(``PositiveIntegerField(default=0, db_index=True)``) and
``Meta.ordering = ["position"]`` — the default sibling rank, and the order every
tree query returns children in.

OPERATION ORDER IS LOAD-BEARING, so this file is hand-ordered rather than
left as ``makemigrations`` emitted it (which put ``RemoveField(thread)`` second):

1. ``AddField(parent)`` — the ``TreeNodeForeignKey`` with ``on_delete=SET_NULL``.
   Added *before* the conversion so the conversion has a destination column.
2. ``AddField(position)`` — every row lands on the field default ``0``.
3. ``RunPython`` — convert the old groups, THEN rank siblings. The rank has to
   read the FINAL ``parent_id``, so it cannot run before step 1's data exists.
4. ``RemoveField(thread)`` — last, because step 3 reads it.

``AlterModelOptions`` (state-only, no SQL — ``ordering`` is not a database
property) sits between the column adds and the backfill so ``position`` is
already in the state when ``ordering`` starts naming it.

REVERSIBILITY
-------------
Every half has a reverse. Django replays the list backwards, undoing one
operation at a time, so the reverse of the forward sequence above is:

    AddField(thread)   ← undoes step 4
    RunPython(reverse) ← undoes step 3; ``thread`` EXISTS again, ``parent``
                          and ``position`` still exist
    RemoveField(position) ← undoes step 2
    RemoveField(parent)   ← undoes step 1

which is why the reverse function can reference all three columns at once —
reconstruction of ``thread`` from ``parent`` is possible only because
``RemoveField`` is the LAST forward operation, not the second.

Losing the hierarchy on the way back is accepted (and is the same trade 0030
made for ``occurred_at``): ``parent_id`` collapses a tree of arbitrary depth
into the flat one-level shape the old model could express, and ``position`` has
no pre-0030 column to map onto at all, so it is zeroed. No row is ever deleted
in either direction.

DEFERRED-FK / DDL TRAP — WHY THE DATA MIGRATION ENDS WITH ``SET CONSTRAINTS``
----------------------------------------------------------------------------
``parent`` and ``thread`` are ``DEFERRABLE INITIALLY DEFERRED`` (Django's
PostgreSQL default), so the re-parenting UPDATE queues constraint-trigger events
that only fire at COMMIT. PostgreSQL refuses ANY DDL on a table with pending
trigger events, and the operation that follows this ``RunPython`` IS DDL —
``RemoveField(thread)`` forward, ``RemoveField(position)`` in reverse. Without
the flush at the end of each half, a database whose links were actually threaded
aborts with:

    cannot ALTER TABLE "incident_socialmedialink" because it has pending
    trigger events

and the migration is never recorded. The dev database held **zero** thread
members when 0031 was authored, so nothing was queued and the bug stayed
invisible there; it only appeared against staging, whose three threaded rows
re-parent and then block the trailing ``RemoveField``. ``flush_deferred_constraints``
(``SET CONSTRAINTS ALL IMMEDIATE``) fires the queued checks immediately and
empties the queue before the DDL runs.

THE CONVERSION IS DEFENSIVE CODE, NOT A DATA RESCUE
---------------------------------------------------
The dev database holds 44 links and **0** thread members, so on the machine this
was authored against the ``thread_id`` loop matches nothing. It is written
anyway and deliberately not short-circuited: a data migration is executed
whenever the migration is applied, which is not necessarily the deploy it was
authored in. The shape it must handle is the real 0030 contract — the root has
``thread_id IS NULL`` and every member points at that root — so
``parent_id = thread_id`` maps a group onto exactly the shape the tree expects,
and the (service-enforced, unrecorded-in-the-DB) "``thread`` always points at a
root" invariant is what makes the result a valid one-level tree with no cycles.

``position`` RANKING RULE
------------------------
``Window(RowNumber())`` partitioned by ``parent_id``, ordered by
``occurred_at ASC, id ASC``, times 10.

* ``occurred_at`` first: a thread reads oldest-first, because the story it tells
  is chronological. This is the same key the flattened member loader ordered by
  in the previous wave, so the existing groups come out in the sequence the UI
  was already showing — and a group re-numbered here lands in the same order.
* ``id ASC`` second, and not decoratively: it is the tie-break that makes the
  order TOTAL. Two links can share an ``occurred_at`` (the UI renders minute
  precision, and 0030 documents grouping posts that share a minute), and
  ``RowNumber`` over a non-total order hands those two rows arbitrary numbers
  that can differ between two runs of the same migration. ``id`` is unique and
  monotonic, so the ranking is deterministic and a re-run is a no-op.
* ``* 10``: the library's own spacing convention —
  ``OrderableTreeNode.save()`` appends at ``max(siblings) + 10`` (and
  ``feincms3``'s ``AbstractPage`` does the same), so positions are ordered keys
  with gaps, not indices. A ``* 1`` backfill would leave every root's first
  child at ``1``, and a later auto-append at ``max + 10 = 11`` would still
  interleave, but a group of ten would occupy the whole ``1..10`` range and a
  *reorder* (G1) that inserts between two existing siblings would have no room
  between them. Ranking at 10/20/30 keeps the gaps the append path assumes.

No ``TreeQuerySet`` anywhere in this file: ``apps.get_model()`` returns a
HISTORICAL model whose manager is a plain ``Manager`` — the tree manager comes
from the abstract base class at import time, which the historical model does not
inherit. A ``Window`` over the plain queryset is the supported way to rank
siblings, and its ``order_by`` is spelled out explicitly — NOT because the
historical ``Meta.ordering`` is unavailable (it is not: ``AlterModelOptions``
runs BEFORE this ``RunPython``, so the state already carries
``ordering=['position']``, verified by replaying ``state_forwards`` operation by
operation) but because a window's rank is a decision about the sequence and must
be total and independent of the model's default. See the ranking rule above.

TIMEZONE TRAP — why ``occurred_at`` is only ever an ORDERING KEY
----------------------------------------------------------------
``USE_TZ = False`` with ``TIME_ZONE = "Asia/Kuala_Lumpur"`` (see MISTAKES.md
2026-09-26): every stored datetime in this table is naive LOCAL wall time. This
migration does not READ a datetime into Python and write it back — the
``Window`` ranking is computed by Postgres over the stored bytes, and only the
integer rank is written. So no ``make_aware`` / ``make_naive`` / ``astimezone``
can be interleaved and the stored values are untouched. If a future revision
needs a Python-side loop here (as 0024's ``normalized_url`` backfill has), that
convention has to be re-checked first.
"""

import django.db.models.deletion
from django.db import connection as default_connection
from django.db import migrations, models
from django.db.models import F, Window
from django.db.models.functions import RowNumber

#: Matches ``OrderableTreeNode.save()``'s ``max(siblings) + 10`` append stride.
POSITION_STEP = 10

#: ``bulk_update`` batch size, same as incident/0024's ``BATCH_SIZE``.
BATCH_SIZE = 500


def flush_deferred_constraints(schema_editor):
    """Force this transaction's queued deferred FK checks to run NOW.

    ``parent`` and ``thread`` are ``DEFERRABLE INITIALLY DEFERRED`` (Django's
    PostgreSQL default). A ``parent_id``/``thread_id`` UPDATE therefore queues
    constraint-trigger events that would only fire at COMMIT — and PostgreSQL
    refuses ANY DDL on a table with pending trigger events:

        cannot ALTER TABLE "incident_socialmedialink" because it has pending
        trigger events

    The operation that follows each ``RunPython`` here is exactly such DDL
    (``RemoveField(thread)`` forward, ``RemoveField(position)`` in reverse), so
    on a database that actually holds threaded rows the whole migration aborts
    half-way. On an empty/never-threaded table no events are queued and the bug
    is invisible — which is why it only surfaced against staging data.
    ``SET CONSTRAINTS ALL IMMEDIATE`` fires the queued checks at once and
    empties the queue, leaving nothing for the DDL to trip over.

    The fallback connection exists for the unit tests, which call these
    functions with a synthetic ``schema_editor=None`` against the test database.
    """
    connection = (
        schema_editor.connection if schema_editor is not None else default_connection
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def convert_threads_to_tree(apps, schema_editor):
    """Fold the flat ``thread`` groups into ``parent``, then rank siblings.

    Defensive by design: as authored this runs against zero thread members, and
    the ``thread_id`` loop is a no-op on a table that has no groups yet. It is
    NOT skipped for that reason — see the module docstring.
    """
    SocialMediaLink = apps.get_model("incident", "SocialMediaLink")

    # 1. Group conversion. A 0030 member pointed at the thread ROOT, which is
    #    exactly what ``parent`` means in the tree, so the mapping is a copy —
    #    no walk, no depth limit, no cycle possible given the old invariant.
    #    A single UPDATE: the ids are read and written in one statement, so no
    #    Python-side round trip can reinterpret a value.
    SocialMediaLink.objects.filter(thread_id__isnull=False).update(
        parent_id=F("thread_id")
    )

    # 2. Sibling ranking. ``partition_by`` groups the NULL parents together, so
    #    every ROOT is ranked in one sequence as well as every parented group —
    #    the roots are a sibling set of their own and need ordering too.
    #    ``RowNumber`` is 1-based, hence the ``* POSITION_STEP``.
    ranked = SocialMediaLink.objects.annotate(
        sibling_rank=Window(
            RowNumber(),
            partition_by=F("parent_id"),
            order_by=[F("occurred_at"), F("id")],
        )
    ).values_list("pk", "sibling_rank")

    batch = []
    for pk, sibling_rank in ranked:
        # Historical model instance carrying only the two fields the write needs;
        # ``bulk_update`` must not touch any other column.
        batch.append(SocialMediaLink(pk=pk, position=sibling_rank * POSITION_STEP))
        if len(batch) >= BATCH_SIZE:
            SocialMediaLink.objects.bulk_update(batch, ["position"])
            batch = []
    if batch:
        SocialMediaLink.objects.bulk_update(batch, ["position"])

    # The ``parent_id`` UPDATE above queued deferred FK checks; ``RemoveField``
    # (the next operation) is DDL and would abort on them. Fire them here.
    flush_deferred_constraints(schema_editor)


def revert_tree_to_threads(apps, schema_editor):
    """Reverse half: rebuild ``thread`` from ``parent``, zero ``position``.

    Runs with all three columns present — see REVERSIBILITY above for the
    operation order that guarantees it.

    ``parent_id = thread_id`` is only an EXACT inverse for a tree of depth ≤ 1.
    A deeper tree (which this migration's forward half cannot produce, but a
    later deploy of the tree feature can) collapses: a grandchild pointed at its
    parent, which is a member rather than a root, and so violates the depth-1
    invariant the 0030 model documented. Reverting a migration restores the
    pre-0031 SHAPE; it is not a guarantee that every row still satisfies an
    invariant that the shape itself cannot express. No row is dropped.
    """
    SocialMediaLink = apps.get_model("incident", "SocialMediaLink")
    # Roots (``parent_id IS NULL``) had ``thread_id IS NULL`` in 0030, so they
    # are left alone rather than written with an explicit NULL.
    SocialMediaLink.objects.exclude(parent_id=None).update(thread_id=F("parent_id"))
    # ``position`` has no pre-0031 counterpart. Zero is the field default the
    # ``AddField`` would have produced, i.e. the closest reversible value.
    SocialMediaLink.objects.all().update(position=0)
    # The ``thread_id`` UPDATE above queued deferred FK checks; the next
    # operation is ``RemoveField(position)``, which is DDL. Fire them here.
    flush_deferred_constraints(schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        (
            "incident",
            "0030_socialmedialink_occurred_at_socialmedialink_thread_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="socialmedialink",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="incident.socialmedialink",
            ),
        ),
        migrations.AddField(
            model_name="socialmedialink",
            name="position",
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.AlterModelOptions(
            name="socialmedialink",
            options={"ordering": ["position"]},
        ),
        migrations.RunPython(convert_threads_to_tree, revert_tree_to_threads),
        migrations.RemoveField(
            model_name="socialmedialink",
            name="thread",
        ),
    ]

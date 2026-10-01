"""The live schema vs. the SDL snapshot, and the snapshot vs. what is COMMITTED.

Two separate guarantees, kept in two tests because they fail for different
reasons and only one of them is about breaking changes:

1. the working-tree snapshot must equal the live schema (a stale snapshot is a
   false promise to the next reader), and
2. the live schema must not break the schema as it was **committed** at ``HEAD``.

Why (2) reads the baseline out of git rather than off disk
------------------------------------------------------------
The working-tree snapshot is regenerated *in the same change* as the schema
edit it records (MISTAKES.md, 2026-09-12) — that is the convention, and it is
the right one. But it makes a working-tree baseline useless as a
breaking-change oracle: the file on disk is by construction the new schema, so
``find_breaking_changes(baseline=file, current=live)`` compares the schema with
itself and is tautologically empty. Such a test can never fail, so the "the only
breaking delta is ``createdAfter``/``createdBefore``" claim it appeared to
enforce was actually verified by hand.

``git show HEAD:<snapshot>`` is the one baseline that is genuinely *different*
from the live schema whenever there are uncommitted schema changes, which is
exactly the window in which a breaking change is worth catching: a developer
edits the schema, has not yet refreshed the snapshot, and CI tells them.

THE ACCEPTED BREAKING CHANGES ARE NAMED, NOT SUPPRESSED
--------------------------------------------------------
``EXPECTED_ACCEPTED_BREAKING_CHANGES`` is the whole reason the check is allowed
to be non-empty, and every entry in it is a DELIBERATE, UN-ALIASED rename or
removal. The rationale is the same in both waves, and it is the reason an alias
is never the cheap way to keep a client working:

* **2026-09-30 (``occurred_at``).** ``socialMediaLinks``' ``createdAfter`` /
  ``createdBefore`` became ``occurredAfter`` / ``occurredBefore``. An alias would
  keep filtering on ``created`` while the queue orders by ``occurred_at``, i.e. a
  filter that looks like it works and is quietly wrong, so a stale client must
  fail loudly with "Unknown argument" instead.
* **2026-10-01 (link tree).** ``SocialMediaLinkScalar.threadId`` / ``threadSize``
  / ``threadLinks`` became ``parentId`` / ``sublinkCount`` / ``sublinks``, and
  ``Mutation.groupSocialMediaLinks``' ``threadId`` arg became ``parentId``. Here
  an alias would be worse than merely quiet: the whole point of the wave is that
  grouping is no longer one-level, so a client still sending ``threadId`` would
  keep getting links nested under the thread ROOT — the old one-level behaviour,
  working — and would never discover that the sublink level it now wants is
  spelled ``parentId``.

They are accepted as a SUBSET check, not an equality check, because the
allowlist has a shelf life: once this wave is committed, ``HEAD`` carries the
renamed fields and the delta shrinks towards the empty set. Equality would then
fail on a clean tree, which is the wrong way round. Two companion tests stop that
from decaying into a blanket suppression:

* ``test_the_accepted_breaking_changes_are_still_real`` pins the LIVE schema —
  every removed name is asserted absent and every replacement asserted present, so
  re-adding an alias fails;
* ``test_every_accepted_removal_is_really_gone`` pins the allowlist to itself —
  each entry must still describe something the live schema genuinely no longer
  has, so an entry left behind after its wave commits is flagged rather than
  quietly tolerated.

and ``assertEqual(len(EXPECTED_ACCEPTED_BREAKING_CHANGES), 6)`` keeps the size
pinned, so the set cannot grow to cover a delta nobody has looked at.

LIMITATION (stated rather than hidden)
--------------------------------------
The breaking-change comparison needs git history, which is not present in every
environment this suite runs in — a CI job that exports the source tree without
``.git``, a container built from a tarball, a package install. The container
image bind-mounts the repo (``.git`` included) so it works here, and
``actions/checkout`` is shallow by default but that is irrelevant: ``git show
HEAD:<path>`` reads the tip commit, not history. Where git genuinely cannot
answer, the test SKIPS with a message saying so rather than passing quietly —
and the allowlist itself is still pinned by the test beside it, so the *scope*
of what is permitted stays machine-enforced even with no history at all.
"""

import re
import subprocess
from pathlib import Path

from django.test import TestCase
from graphql.utilities import build_schema, find_breaking_changes

from rosak.schema import schema

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "schema.graphql"

# The deliberate, documented breaking delta: SIX entries, all of them un-aliased
# renames/removals from the two waves, and nothing else — see the module
# docstring for why each rename is right and why none may be re-aliased.
EXPECTED_ACCEPTED_BREAKING_CHANGES = {
    # 2026-09-30, occurred_at: the queue's window filters.
    "Query.socialMediaLinks arg createdAfter was removed.",
    "Query.socialMediaLinks arg createdBefore was removed.",
    # 2026-10-01, link tree: the flat one-level thread became a nested tree.
    "SocialMediaLinkScalar.threadId was removed.",
    "SocialMediaLinkScalar.threadSize was removed.",
    "SocialMediaLinkScalar.threadLinks was removed.",
    "Mutation.groupSocialMediaLinks arg threadId was removed.",
}

#: ``EXPECTED_ACCEPTED_BREAKING_CHANGES``'s exact size. Pinned so the allowlist
#: cannot be widened to swallow a delta nobody has read: a seventh entry fails
#: here first, with a legible reason, rather than quietly authorising whatever
#: the next wave breaks.
EXPECTED_ACCEPTED_BREAKING_CHANGE_COUNT = 6

#: ``find_breaking_changes`` renders its two descriptions we allow here in
#: exactly these shapes — note the ARG shape carries the *owning* type AND the
#: field it is an argument of (``Mutation.groupSocialMediaLinks``), which is why
#: it needs its own pattern. Parsed rather than matched against a hand-written
#: table so the anti-rot test below cannot disagree with the oracle that
#: produced the allowlist: an unparseable entry fails loudly instead of being
#: skipped.
_REMOVED_FIELD = re.compile(r"^(?P<type>[A-Za-z_]\w*)\.(?P<field>\w+) was removed\.$")
_REMOVED_ARG = re.compile(
    r"^(?P<owner>[A-Za-z_]\w*)\.(?P<field>\w+) arg (?P<arg>\w+) was removed\.$"
)


def _committed_baseline_sdl() -> tuple[str | None, str]:
    """The snapshot as committed at ``HEAD``.

    Returns ``(sdl, "")`` on success or ``(None, reason)`` when git cannot
    answer. The reason is surfaced verbatim in the skip message: a test that
    stops guarding something must say which something.

    ``-c safe.directory=*`` is not optional. The container runs as a different
    user from whoever owns the bind-mounted checkout, so git refuses with
    "detected dubious ownership" and the baseline would silently become
    unavailable. Passing it per-invocation keeps the host's global git config
    untouched.
    """
    # .../rosak_backend/rosak/tests/snapshots/schema.graphql -> repo root
    repo_root = SNAPSHOT_PATH.parents[3]
    rel_path = SNAPSHOT_PATH.relative_to(repo_root).as_posix()
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "-C",
                str(repo_root),
                "show",
                f"HEAD:{rel_path}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # git not installed, or not executable
        return None, f"git is unavailable in this environment ({exc})"
    if result.returncode != 0:
        return None, (
            f"`git show HEAD:{rel_path}` failed: "
            f"{result.stderr.strip() or 'unknown error'}"
        )
    return result.stdout, ""


class TestSchemaSnapshot(TestCase):
    def test_schema_snapshot_matches_committed_baseline(self):
        """Ensure current schema matches the committed SDL snapshot baseline."""
        self.assertTrue(
            SNAPSHOT_PATH.exists(),
            f"Snapshot file not found at {SNAPSHOT_PATH}",
        )
        baseline_sdl = SNAPSHOT_PATH.read_text(encoding="utf-8").strip()
        current_sdl = str(schema).strip()

        self.assertEqual(
            current_sdl,
            baseline_sdl,
            "GraphQL schema SDL differs from snapshot baseline in snapshots/schema.graphql",
        )

    def test_the_accepted_breaking_changes_are_still_real(self):
        """The allowlist must describe THIS schema, or it is a suppression.

        Checks the live schema directly instead of going through git, so the
        permitted delta stays pinned even where there is no history to diff
        against. It also fails if someone re-adds an old name as an ALIAS: each
        accepted breaking change was a removal, so an alias that brings the old
        spelling back means the rename was undone and the allowlist above is
        describing a delta that no longer exists.
        """
        # ``Field.args`` maps NAME -> GraphQLArgument, so the key is the name.
        query = schema._schema.query_type.fields
        mutation = schema._schema.mutation_type.fields
        link_fields = set(schema._schema.type_map["SocialMediaLinkScalar"].fields)

        queue_args = set(query["socialMediaLinks"].args)
        group_args = set(mutation["groupSocialMediaLinks"].args)

        # --- 2026-09-30: createdAfter/createdBefore -> occurredAfter/Before ---
        self.assertIn("occurredAfter", queue_args)
        self.assertIn("occurredBefore", queue_args)
        self.assertNotIn(
            "createdAfter",
            queue_args,
            msg=(
                "createdAfter is back on socialMediaLinks. The rename to "
                "occurredAfter was deliberate and unaliased so a stale client "
                "fails loudly; an alias here filters on created while the queue "
                "orders by occurred_at. Update the module docstring, this test "
                "and EXPECTED_ACCEPTED_BREAKING_CHANGES deliberately if that "
                "decision is being reversed."
            ),
        )
        self.assertNotIn("createdBefore", queue_args)

        # --- 2026-10-01: the flat one-level thread -> an ordered nested tree ---
        # The replacements must be present, so a rename that only half landed
        # (removed the old name, never added the new one) cannot pass as
        # "the breaking change was accepted".
        self.assertIn("parentId", group_args)
        self.assertIn("parentId", link_fields)
        self.assertIn("isThreadRoot", link_fields)
        self.assertIn("sublinkCount", link_fields)
        self.assertIn("sublinks", link_fields)

        for name in ("threadId", "threadSize", "threadLinks"):
            self.assertNotIn(
                name,
                link_fields,
                msg=(
                    f"{name} is back on SocialMediaLinkScalar. The tree wave "
                    "renamed it and deliberately shipped no compatibility alias: "
                    "the point of nesting is that a stale client must get a "
                    "loud 'Unknown field' instead of quietly receiving the old "
                    "one-level grouping it already understood. Update the module "
                    "docstring, this test and EXPECTED_ACCEPTED_BREAKING_CHANGES "
                    "deliberately if that decision is being reversed."
                ),
            )
        self.assertNotIn(
            "threadId",
            group_args,
            msg=(
                "threadId is back on groupSocialMediaLinks. An alias here is the "
                "worst case of the three: it would keep accepting the old "
                "argument and go on nesting links under the thread ROOT, which "
                "is exactly the one-level behaviour the tree wave replaced, so "
                "the client would never discover parentId."
            ),
        )

        # Six entries in, six removed names out — so the allowlist cannot quietly
        # grow to cover a delta nobody has looked at.
        self.assertEqual(
            len(EXPECTED_ACCEPTED_BREAKING_CHANGES),
            EXPECTED_ACCEPTED_BREAKING_CHANGE_COUNT,
        )

    def test_every_accepted_removal_is_really_gone(self):
        """Anti-rot, from the other direction: each allowlist entry must be REAL.

        The subset check in ``test_no_breaking_changes_detected`` can only ever
        fail on an UNEXPECTED change, so it is silent about a *stale* entry: once
        this wave is committed, ``HEAD`` carries the renamed surface, the diff
        shrinks towards the empty set, and the entry describing a removal that
        is now the baseline rather than a delta stops being checked by anything.
        Left alone it would sit there as permission for the next wave's
        same-named break.

        This test closes that direction: every entry must name something the
        LIVE schema genuinely no longer has. A leftover entry, a typo, or a
        blanket-suppression entry added on a hunch all fail here, and an
        unparseable description fails rather than being skipped.
        """
        graphql_schema = schema._schema
        for description in sorted(EXPECTED_ACCEPTED_BREAKING_CHANGES):
            arg_match = _REMOVED_ARG.match(description)
            field_match = _REMOVED_FIELD.match(description)
            self.assertTrue(
                arg_match or field_match,
                msg=(
                    f"{description!r} is not a shape find_breaking_changes "
                    "produces, so this test cannot verify it. Add a pattern "
                    "rather than skipping it."
                ),
            )
            match = arg_match or field_match
            # ``_REMOVED_FIELD`` names the type directly; ``_REMOVED_ARG`` names
            # the owning type as ``owner`` because the description is
            # ``<Owner>.<field> arg <argName> was removed.``
            type_name = match.group("owner") if arg_match else match.group("type")
            graphql_type = graphql_schema.type_map.get(type_name)
            self.assertIsNotNone(
                graphql_type,
                msg=f"{description!r} names a type the live schema does not have.",
            )
            if arg_match:
                # The FIELD is supposed to still exist — only its ARG is gone —
                # so looking it up is the assertion's setup, not a lookup that
                # can fail for the reason being tested.
                self.assertNotIn(
                    match.group("arg"),
                    graphql_type.fields[match.group("field")].args,
                    msg=(
                        f"{description!r} is allowlisted but {match.group('arg')} "
                        f"is still an argument of {type_name}."
                        f"{match.group('field')}. Either the alias came back or "
                        "the entry is stale; both need a deliberate decision."
                    ),
                )
            else:
                # The removed FIELD must simply be absent, so it is deliberately
                # NOT looked up: a lookup would raise KeyError, which reads as an
                # error rather than as the clean assertion it is.
                self.assertNotIn(
                    match.group("field"),
                    graphql_type.fields,
                    msg=(
                        f"{description!r} is allowlisted but "
                        f"{type_name}.{match.group('field')} still exists. "
                        "Either the alias came back or the entry is stale; both "
                        "need a deliberate decision."
                    ),
                )

    def test_no_breaking_changes_detected(self):
        """No breaking changes vs. the snapshot as COMMITTED at ``HEAD``.

        Every reported change must be one of
        ``EXPECTED_ACCEPTED_BREAKING_CHANGES``; anything else fails. See the
        module docstring for why the baseline comes from git and why the named
        removals are accepted rather than suppressed.
        """
        baseline_sdl, unavailable = _committed_baseline_sdl()
        if baseline_sdl is None:
            self.skipTest(
                "breaking-change check did not run: "
                f"{unavailable}. The live schema is still compared against the "
                "working-tree snapshot by the test above, and the accepted "
                "delta is still pinned by "
                "test_the_accepted_breaking_changes_are_still_real, but the "
                "diff against committed history is NOT enforced in this "
                "environment."
            )

        self.assertTrue(
            baseline_sdl.strip(),
            "The snapshot committed at HEAD is empty; it cannot serve as a "
            "breaking-change baseline.",
        )

        baseline_schema = build_schema(baseline_sdl)
        current_schema = schema._schema

        breaking_changes = {
            change.description
            for change in find_breaking_changes(baseline_schema, current_schema)
        }
        unexpected = breaking_changes - EXPECTED_ACCEPTED_BREAKING_CHANGES
        self.assertEqual(
            unexpected,
            set(),
            msg=(
                f"Unexpected breaking changes vs. the committed baseline: "
                f"{sorted(unexpected)}. The only accepted delta is "
                f"{sorted(EXPECTED_ACCEPTED_BREAKING_CHANGES)} "
                "(the occurred_at window filters and the link-tree thread "
                "fields/argument renames, all shipped un-aliased). Either "
                "restore the removed surface, or accept the new delta "
                "deliberately by naming it in "
                "EXPECTED_ACCEPTED_BREAKING_CHANGES, bumping "
                "EXPECTED_ACCEPTED_BREAKING_CHANGE_COUNT, and saying why here."
            ),
        )

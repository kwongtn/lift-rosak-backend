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
to be non-empty. The 2026-09-30 wave renamed ``socialMediaLinks``'
``createdAfter``/``createdBefore`` to ``occurredAfter``/``occurredBefore`` with
**no alias**, on purpose: an alias would keep filtering on ``created`` while the
queue orders by ``occurred_at``, i.e. a filter that looks like it works and is
quietly wrong, so a stale client must fail loudly with "Unknown argument"
instead. Those two removals are therefore the accepted delta, listed by name.

They are accepted as a SUBSET check, not an equality check, because the
allowlist has a shelf life: once this wave is committed, ``HEAD`` carries the
renamed args and the delta shrinks to the empty set. Equality would then fail on
a clean tree, which is the wrong way round. ``test_the_accepted_breaking_changes
_are_still_real`` pins the allowlist against the live schema so it cannot rot
into a blanket suppression while the subset check lets it drain.

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

import subprocess
from pathlib import Path

from django.test import TestCase
from graphql.utilities import build_schema, find_breaking_changes

from rosak.schema import schema

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "schema.graphql"

# The deliberate, documented breaking delta. Two ARG_REMOVED entries, nothing
# else — see the module docstring for why the rename is right and why it must
# not be re-aliased.
EXPECTED_ACCEPTED_BREAKING_CHANGES = {
    "Query.socialMediaLinks arg createdAfter was removed.",
    "Query.socialMediaLinks arg createdBefore was removed.",
}


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

        Checks the live ``socialMediaLinks`` arguments directly instead of going
        through git, so the permitted delta stays pinned even where there is no
        history to diff against. It also fails if someone re-adds the old
        argument names: the accepted breaking changes were those two removals,
        so an alias that brings them back means the rename was undone and the
        allowlist above is describing a delta that no longer exists.
        """
        # ``Field.args`` maps NAME -> GraphQLArgument, so the key is the name.
        arg_names = set(schema._schema.query_type.fields["socialMediaLinks"].args)

        self.assertIn("occurredAfter", arg_names)
        self.assertIn("occurredBefore", arg_names)
        self.assertNotIn(
            "createdAfter",
            arg_names,
            msg=(
                "createdAfter is back on socialMediaLinks. The rename to "
                "occurredAfter was deliberate and unaliased so a stale client "
                "fails loudly; an alias here filters on created while the queue "
                "orders by occurred_at. Update the module docstring, this test "
                "and EXPECTED_ACCEPTED_BREAKING_CHANGES deliberately if that "
                "decision is being reversed."
            ),
        )
        self.assertNotIn("createdBefore", arg_names)

        # Two entries in, two removed args out — so the allowlist cannot quietly
        # grow to cover a delta nobody has looked at.
        self.assertEqual(len(EXPECTED_ACCEPTED_BREAKING_CHANGES), 2)

    def test_no_breaking_changes_detected(self):
        """No breaking changes vs. the snapshot as COMMITTED at ``HEAD``.

        Every reported change must be one of
        ``EXPECTED_ACCEPTED_BREAKING_CHANGES``; anything else fails. See the
        module docstring for why the baseline comes from git and why the two
        named removals are accepted rather than suppressed.
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
                "(the createdAfter/createdBefore -> occurredAfter/occurredBefore "
                "rename). Either restore the removed surface, or accept the new "
                "delta deliberately by naming it in "
                "EXPECTED_ACCEPTED_BREAKING_CHANGES and saying why here."
            ),
        )

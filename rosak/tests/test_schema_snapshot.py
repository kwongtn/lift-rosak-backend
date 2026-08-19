from pathlib import Path

from django.test import TestCase
from graphql.utilities import build_schema, find_breaking_changes

from rosak.schema import schema

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "schema.graphql"


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

    def test_no_breaking_changes_detected(self):
        """Ensure no breaking changes exist compared to the baseline SDL."""
        self.assertTrue(
            SNAPSHOT_PATH.exists(),
            f"Snapshot file not found at {SNAPSHOT_PATH}",
        )
        baseline_sdl = SNAPSHOT_PATH.read_text(encoding="utf-8")
        baseline_schema = build_schema(baseline_sdl)
        current_schema = schema._schema

        breaking_changes = find_breaking_changes(baseline_schema, current_schema)
        self.assertEqual(
            breaking_changes,
            [],
            f"Breaking changes detected in GraphQL schema: {breaking_changes}",
        )

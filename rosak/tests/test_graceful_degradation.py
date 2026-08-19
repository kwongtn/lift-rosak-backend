from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import DatabaseError, OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from dotmap import DotMap

from operation.models import Line
from rosak.context import ContextLoaders


def get_graphql_context(user=None):
    return DotMap(
        {
            "loaders": ContextLoaders,
            "request": None,
            "response": None,
            "user": user,
        }
    )


def execute_graphql(query: str, variables: dict | None = None, user=None):
    from rosak.schema import schema

    context = get_graphql_context(user=user)
    return async_to_sync(schema.execute)(
        query, variable_values=variables, context_value=context
    )


class GracefulDegradationSettingsTests(SimpleTestCase):
    def test_settings_jejak_disabled_databases(self):
        with override_settings(JEJAK_ENABLED=False):
            self.assertFalse(settings.JEJAK_ENABLED)

    def test_healthcheck_excludes_timescale(self):
        from health_check.plugins import plugin_dir

        registered_classes = [cls for cls, _opts in plugin_dir._registry]
        for cls in registered_classes:
            self.assertNotIn("timescale", cls.__name__.lower())

    def test_schema_imports_successfully_without_jejak(self):
        with override_settings(JEJAK_ENABLED=False):
            try:
                import importlib

                import rosak.schema

                importlib.reload(rosak.schema)
                schema = rosak.schema.schema  # noqa: F841
                query_type = rosak.schema.Query

                base_names = [base.__name__ for base in query_type.__bases__]
                self.assertNotIn("JejakScalars", base_names)
                self.assertIn("OperationScalars", base_names)
            except ImportError as e:
                self.fail(f"Schema import failed without jejak: {e}")


class GracefulDegradationGraphQLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.line = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#d32f2f",
        )

    def test_non_jejak_queries_work_normally(self):
        result = execute_graphql(
            """
            query {
                lines {
                    id
                    code
                    displayName
                }
            }
            """
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)
        codes = [line["code"] for line in result.data["lines"]]
        self.assertIn("KJL", codes)

    @override_settings(JEJAK_ENABLED=False)
    def test_jejak_locations_returns_error_when_jejak_disabled(self):
        result = execute_graphql(
            """
            query {
                locations {
                    id
                }
            }
            """
        )
        self.assertIsNotNone(result.errors)
        self.assertTrue(
            any(
                "Jejak service unavailable" in str(err.message) for err in result.errors
            )
        )

    @override_settings(JEJAK_ENABLED=False)
    def test_jejak_buses_returns_error_when_jejak_disabled(self):
        result = execute_graphql(
            """
            query {
                buses {
                    id
                }
            }
            """
        )
        self.assertIsNotNone(result.errors)
        self.assertTrue(
            any(
                "Jejak service unavailable" in str(err.message) for err in result.errors
            )
        )

    @override_settings(JEJAK_ENABLED=False)
    def test_jejak_locations_count_returns_error_when_jejak_disabled(self):
        result = execute_graphql(
            """
            query {
                locationsCount
            }
            """
        )
        self.assertIsNotNone(result.errors)
        self.assertTrue(
            any(
                "Jejak service unavailable" in str(err.message) for err in result.errors
            )
        )

    @override_settings(JEJAK_ENABLED=True)
    def test_jejak_locations_returns_error_on_operational_error(self):
        with patch(
            "jejak.models.Location.objects.all",
            side_effect=OperationalError("could not connect to server"),
        ):
            result = execute_graphql(
                """
                query {
                    locations {
                        id
                    }
                }
                """
            )
            self.assertIsNotNone(result.errors)
            self.assertTrue(
                any(
                    "Jejak database unavailable" in str(err.message)
                    for err in result.errors
                )
            )

    @override_settings(JEJAK_ENABLED=True)
    def test_jejak_buses_returns_error_on_database_error(self):
        with patch(
            "jejak.models.Bus.objects.all",
            side_effect=DatabaseError("relation does not exist"),
        ):
            result = execute_graphql(
                """
                query {
                    buses {
                        id
                    }
                }
                """
            )
            self.assertIsNotNone(result.errors)
            self.assertTrue(
                any(
                    "Jejak database unavailable" in str(err.message)
                    for err in result.errors
                )
            )

    @override_settings(JEJAK_ENABLED=True)
    def test_jejak_locations_count_returns_error_on_operational_error(self):
        with patch(
            "jejak.models.Location.objects.filter",
            side_effect=OperationalError("could not connect to server"),
        ):
            result = execute_graphql(
                """
                query {
                    locationsCount(filters: { id: "1", busId: "1", dtReceivedRange: ["2026-01-01T00:00:00"], dtGpsRange: ["2026-01-01T00:00:00"] })
                }
                """
            )
            self.assertIsNotNone(result.errors)
            self.assertTrue(
                any(
                    "Jejak database unavailable" in str(err.message)
                    for err in result.errors
                )
            )

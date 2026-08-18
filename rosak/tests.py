import copy

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase
from dotmap import DotMap
from strawberry import Schema

from operation.models import Line
from rosak.context import ContextLoaders
from rosak.schema import schema


def get_graphql_context(user=None):
    return DotMap(
        {
            "loaders": copy.deepcopy(ContextLoaders),
            "request": None,
            "response": None,
            "user": user,
        }
    )


def execute_graphql(query: str, variables: dict | None = None, user=None):
    context = get_graphql_context(user=user)
    return async_to_sync(schema.execute)(
        query, variable_values=variables, context_value=context
    )


async def execute_graphql_async(query: str, variables: dict | None = None, user=None):
    context = get_graphql_context(user=user)
    return await schema.execute(query, variable_values=variables, context_value=context)


class RosakSchemaTests(SimpleTestCase):
    def test_schema_compiles_successfully(self):
        self.assertIsInstance(schema, Schema)

    def test_query_lines_field_definition(self):
        query = """
            query {
                lines {
                    id
                }
            }
        """  # noqa: F841
        # Testing synchronous parsing / type definition
        doc = schema.get_type_by_name("Query")
        self.assertIsNotNone(doc)
        self.assertIn("lines", [f.name for f in doc.fields])

    def test_root_query_and_mutation_fields_present(self):
        query_fields = [f.name for f in schema.get_type_by_name("Query").fields]
        for field in [
            "lines",
            "stations",
            "vehicles",
            "vehicleTypes",
            "assets",
            "events",
            "events_count",
            "calendar_incidents",
            "vehicle_incidents",
            "station_incidents",
        ]:
            self.assertIn(field, query_fields)

        mutation_fields = [f.name for f in schema.get_type_by_name("Mutation").fields]
        for field in ["add_event", "delete_event", "mark_as_read"]:
            self.assertIn(field, mutation_fields)


class RosakSchemaExecutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.line = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#d32f2f",
        )

    def test_lines_query_executes_against_orm(self):
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
        codes = [line["code"] for line in result.data["lines"]]
        self.assertIn("KJL", codes)

    def test_events_query_executes_with_dataloader_context(self):
        result = execute_graphql(
            """
            query {
                events {
                    id
                    spottingDate
                    status
                }
            }
            """
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["events"], [])

    def test_login_gated_mutation_rejects_anonymous_user(self):
        result = execute_graphql(
            """
            mutation {
                deleteEvent(input: { id: "1" }) {
                    ok
                }
            }
            """
        )
        self.assertIsNotNone(result.errors)

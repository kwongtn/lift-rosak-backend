"""Schema-assembly tests: the full GraphQL contract builds and exposes the waves' fields."""

import pytest
import strawberry


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Mutation, Query

    return strawberry.Schema(query=Query, mutation=Mutation)


def _field_names(schema, type_name: str) -> set[str]:
    return {field.name for field in schema.get_type_by_name(type_name).fields}


@pytest.mark.django_db
def test_root_query_exposes_incident_fields():
    schema = _build_schema()
    query_fields = _field_names(schema, "Query")

    expected = {
        "calendar_incidents",
        "vehicle_incidents",
        "station_incidents",
        "calendar_incidents_by_severity_count",
        "pending_calendar_incidents",
        "social_media_links",
        "calendar_incident_categories",
    }
    missing = expected - query_fields
    assert not missing, f"missing query fields: {missing}"


@pytest.mark.django_db
def test_root_mutation_exposes_all_incident_mutations():
    schema = _build_schema()
    mutation_fields = _field_names(schema, "Mutation")

    expected = {
        "create_calendar_incident",
        "update_calendar_incident",
        "submit_calendar_incident",
        "approve_calendar_incident",
        "reject_calendar_incident",
        "delete_calendar_incident",
        "create_chronology",
        "update_chronology",
        "approve_chronology",
        "reorder_chronology",
        "delete_chronology",
        "upvote",
        "downvote",
        "remove_vote",
        "submit_social_media_link",
        "mark_social_media_link_completed",
        "extract_data_from_url",
    }
    missing = expected - mutation_fields
    assert not missing, f"missing mutations: {missing}"


@pytest.mark.django_db
def test_incident_input_and_enum_types_are_in_schema():
    schema = _build_schema()
    sdl = schema.as_str()
    for name in (
        "CalendarIncidentInput",
        "CalendarIncidentChronologyInput",
        "ExtractDataInput",
        "SocialMediaLinkInput",
        "CalendarIncidentSeverity",
    ):
        assert name in sdl, f"{name} missing from schema types"

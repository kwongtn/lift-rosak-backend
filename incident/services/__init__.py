"""Incident mutation business logic, split by aggregate.

Modules here are deliberately free of Strawberry types: resolvers in
incident/schema translate GraphQL inputs into the write-dataclasses exposed
below and convert service errors into GraphQLErrors, so unit tests exercise
the ORM directly.
"""

from .access import get_incident, is_author, may_edit
from .chronologies import (
    ChronologyUpdate,
    approve_chronology,
    create_chronology,
    delete_chronology,
    reorder_chronology,
    update_chronology,
)
from .errors import (
    ConcurrencyConflictError,
    IncidentNotEditableError,
    IncidentServiceError,
)
from .incidents import (
    ChronologyWrite,
    IncidentWrite,
    UpdateResult,
    approve_incident,
    create_incident,
    delete_incident,
    reject_incident,
    update_incident,
)
from .social_links import (
    SocialMediaLinkWrite,
    mark_social_media_link_completed,
    submit_social_media_link,
)
from .votes import remove_incident_vote, set_incident_vote

__all__ = [
    "ChronologyUpdate",
    "ChronologyWrite",
    "ConcurrencyConflictError",
    "IncidentNotEditableError",
    "IncidentServiceError",
    "IncidentWrite",
    "SocialMediaLinkWrite",
    "UpdateResult",
    "approve_chronology",
    "approve_incident",
    "create_chronology",
    "create_incident",
    "delete_chronology",
    "delete_incident",
    "get_incident",
    "is_author",
    "mark_social_media_link_completed",
    "may_edit",
    "reorder_chronology",
    "reject_incident",
    "remove_incident_vote",
    "set_incident_vote",
    "submit_social_media_link",
    "update_chronology",
    "update_incident",
]

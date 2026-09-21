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
    approve_chronology_deletion,
    create_chronology,
    delete_chronology,
    reject_chronology_deletion,
    reorder_chronology,
    request_chronology_deletion,
    update_chronology,
)
from .errors import (
    ConcurrencyConflictError,
    FeedLinkValidationError,
    IncidentNotEditableError,
    IncidentServiceError,
)
from .feed_links import (
    FeedLinkResult,
    submit_feed_link,
)
from .incidents import (
    ChronologyWrite,
    IncidentWrite,
    UpdateResult,
    approve_incident,
    create_incident,
    delete_incident,
    reject_incident,
    submit_incident,
    update_incident,
)
from .page_title import fetch_page_title
from .social_links import (
    SocialMediaLinkWrite,
    delete_social_media_link,
    mark_social_media_link_completed,
    submit_social_media_link,
    update_social_media_link,
)
from .votes import (
    remove_chronology_vote,
    remove_incident_vote,
    remove_social_media_link_vote,
    set_chronology_vote,
    set_incident_vote,
    set_social_media_link_vote,
)

__all__ = [
    "ChronologyUpdate",
    "ChronologyWrite",
    "ConcurrencyConflictError",
    "FeedLinkResult",
    "FeedLinkValidationError",
    "IncidentNotEditableError",
    "IncidentServiceError",
    "IncidentWrite",
    "SocialMediaLinkWrite",
    "UpdateResult",
    "approve_chronology",
    "approve_chronology_deletion",
    "approve_incident",
    "create_chronology",
    "create_incident",
    "delete_chronology",
    "delete_incident",
    "delete_social_media_link",
    "fetch_page_title",
    "get_incident",
    "is_author",
    "mark_social_media_link_completed",
    "may_edit",
    "reject_chronology_deletion",
    "reject_incident",
    "remove_chronology_vote",
    "reorder_chronology",
    "remove_incident_vote",
    "remove_social_media_link_vote",
    "request_chronology_deletion",
    "set_chronology_vote",
    "set_incident_vote",
    "set_social_media_link_vote",
    "submit_feed_link",
    "submit_incident",
    "submit_social_media_link",
    "update_chronology",
    "update_social_media_link",
    "update_incident",
]

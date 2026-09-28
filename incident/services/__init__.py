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
    OfficialPostFetchError,
    OfficialPostIngestError,
)
from .feed_links import (
    FeedLinkResult,
    submit_feed_link,
    submit_line_status_report,
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
from .official_posts import (
    IngestSummary,
    RawPost,
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
    load_fixture_posts,
    resolve_handle_for_user_id,
    tweet_to_raw_post,
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
from .x_webhooks import (
    WebhookIngestResult,
    crc_response_token,
    has_signing_secret,
    ingest_webhook_payload,
    sign_body,
    verify_webhook_signature,
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
    "IngestSummary",
    "OfficialPostFetchError",
    "OfficialPostIngestError",
    "RawPost",
    "SocialMediaLinkWrite",
    "UpdateResult",
    "WebhookIngestResult",
    "approve_chronology",
    "approve_chronology_deletion",
    "approve_incident",
    "create_chronology",
    "create_incident",
    "crc_response_token",
    "delete_chronology",
    "delete_incident",
    "delete_social_media_link",
    "fetch_page_title",
    "fetch_user_posts",
    "get_incident",
    "get_system_author",
    "has_signing_secret",
    "ingest_posts",
    "ingest_webhook_payload",
    "is_author",
    "latest_post_id",
    "load_fixture_posts",
    "mark_social_media_link_completed",
    "may_edit",
    "reject_chronology_deletion",
    "reject_incident",
    "remove_chronology_vote",
    "reorder_chronology",
    "remove_incident_vote",
    "remove_social_media_link_vote",
    "request_chronology_deletion",
    "resolve_handle_for_user_id",
    "set_chronology_vote",
    "set_incident_vote",
    "set_social_media_link_vote",
    "sign_body",
    "submit_feed_link",
    "submit_incident",
    "submit_line_status_report",
    "submit_social_media_link",
    "tweet_to_raw_post",
    "update_chronology",
    "update_social_media_link",
    "update_incident",
    "verify_webhook_signature",
]

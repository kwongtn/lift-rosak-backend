"""Typed failures raised by incident services; resolvers map them to GraphQLErrors."""


class IncidentServiceError(Exception):
    """Base class for mutation business-rule failures."""


class ConcurrencyConflictError(IncidentServiceError):
    """The caller's version is stale; someone else edited the incident first."""


class IncidentNotEditableError(IncidentServiceError):
    """The actor may not modify this incident in its current state."""


class FeedLinkValidationError(IncidentServiceError):
    """The feed submission is missing a required association (e.g. status)."""


class LineStatusValidationError(IncidentServiceError):
    """A line-status query parameter is out of range (e.g. dayStartHour)."""


class OfficialPostFetchError(IncidentServiceError):
    """An official post could not be fetched or decoded.

    Raised on a non-2xx response, a timeout or an unparseable payload. The
    message is sanitized upstream: never the raw response body, never the
    bearer token.
    """


class OfficialPostIngestError(IncidentServiceError):
    """An official post cannot be ingested (e.g. the system author is missing)."""

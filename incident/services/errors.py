"""Typed failures raised by incident services; resolvers map them to GraphQLErrors."""


class IncidentServiceError(Exception):
    """Base class for mutation business-rule failures."""


class ConcurrencyConflictError(IncidentServiceError):
    """The caller's version is stale; someone else edited the incident first."""


class IncidentNotEditableError(IncidentServiceError):
    """The actor may not modify this incident in its current state."""

import logging
from datetime import timedelta

from django.utils.timezone import now
from safedelete.models import HARD_DELETE

from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
from rosak.celery import app as celery_app

logger = logging.getLogger(__name__)

SOFT_DELETED_RETENTION = timedelta(days=90)
REJECTED_RETENTION = timedelta(days=30)


@celery_app.task()
def purge_soft_deleted_incidents() -> int:
    """Hard-delete incidents soft-deleted more than 90 days ago."""
    cutoff = now() - SOFT_DELETED_RETENTION
    expired = CalendarIncident.deleted_objects.filter(deleted__lt=cutoff)

    count = 0
    for incident in expired:
        incident.delete(force_policy=HARD_DELETE)
        count += 1

    logger.info("Purged %d soft-deleted incidents past retention", count)
    return count


@celery_app.task()
def purge_rejected_incidents() -> int:
    """Hard-delete visible REJECTED incidents unchanged for over 30 days.

    Soft-deleted rows are intentionally out of scope here — they belong to
    purge_soft_deleted_incidents regardless of status.
    """
    cutoff = now() - REJECTED_RETENTION
    expired = CalendarIncident.objects.filter(
        status=CalendarIncidentStatus.REJECTED,
        modified__lt=cutoff,
    )

    count = 0
    for incident in expired:
        incident.delete(force_policy=HARD_DELETE)
        count += 1

    logger.info("Purged %d rejected incidents past retention", count)
    return count

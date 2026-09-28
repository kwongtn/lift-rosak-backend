import datetime
import os

from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rosak.settings")

app = Celery("rosak")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Beat schedule
beat_schedule = {
    "cleanup_expired_verification_codes": {
        "task": "common.tasks.cleanup_expired_verification_codes",
        "schedule": datetime.timedelta(minutes=10),
    },
    "cleanup_temporary_media": {
        "task": "common.tasks.cleanup_temporary_media_task",
        "schedule": datetime.timedelta(minutes=1),
    },
}

if "telegram_provider" in settings.INSTALLED_APPS:
    beat_schedule["cleanup_telegram_logs"] = {
        "task": "telegram_provider.tasks.cleanup_telegram_logs",
        "schedule": crontab(hour="3", minute="0"),
    }

if "chartography" in settings.INSTALLED_APPS:
    beat_schedule["aggregate_line_vehicle_status_mlptf"] = {
        "task": "chartography.tasks.aggregate_line_vehicle_status_mlptf_task",
        "schedule": crontab(hour="5", minute="0"),
    }
    beat_schedule["aggregate_line_vehicle_status_mtrec"] = {
        "task": "chartography.tasks.aggregate_line_vehicle_status_mtrec_task",
        "schedule": crontab(hour="1", minute="0"),
    }

if "spotting" in settings.INSTALLED_APPS:
    beat_schedule["report_spotting_today"] = {
        "task": "spotting.tasks.report_spotting_today",
        "schedule": crontab(hour="0", minute="0"),
    }


# Poll the tracked official X accounts. Ships inert: the task itself checks
# OFFICIAL_POST_INGESTION_ENABLED, OFFICIAL_POST_POLLING_ENABLED and
# X_API_BEARER_TOKEN and no-ops without them. expires < the 5-minute period so
# a wedged run is not re-dispatched on top of itself; time_limit caps a hung
# fetch.
def official_post_polling_entry() -> dict | None:
    """The opt-in beat entry for official-post polling, or None when disabled."""
    if not settings.OFFICIAL_POST_POLLING_ENABLED:
        return None
    return {
        "task": "incident.tasks.ingest_official_posts",
        "schedule": crontab(minute="*/5"),
        "options": {"expires": 240, "time_limit": 180},
    }


if "incident" in settings.INSTALLED_APPS:
    beat_schedule["purge_soft_deleted_incidents"] = {
        "task": "incident.tasks.purge_soft_deleted_incidents",
        "schedule": crontab(hour="3", minute="0"),
    }
    beat_schedule["purge_rejected_incidents"] = {
        "task": "incident.tasks.purge_rejected_incidents",
        "schedule": crontab(hour="3", minute="30"),
    }
    entry = official_post_polling_entry()
    if entry is not None:
        beat_schedule["ingest_official_posts"] = entry

app.conf.beat_schedule = beat_schedule


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")

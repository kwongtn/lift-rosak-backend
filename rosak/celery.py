import datetime
import os

from celery import Celery
from celery.schedules import crontab

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
app.conf.beat_schedule = {
    "cleanup_temporary_media": {
        "task": "common.tasks.cleanup_temporary_media_task",
        "schedule": datetime.timedelta(minutes=1),
    },
    "aggregate_line_vehicle_status_mlptf": {
        "task": "chartography.tasks.aggregate_line_vehicle_status_mlptf_task",
        "schedule": crontab(hour="5", minute="0"),
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")

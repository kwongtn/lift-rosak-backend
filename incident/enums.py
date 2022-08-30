from django.db import models


class IncidentSeverity(models.TextChoices):
    CRITICAL = "CRITICAL"
    TRIVIA = "TRIVIA"
    STATUS = "STATUS"

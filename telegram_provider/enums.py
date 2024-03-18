from django.db.models import IntegerChoices


class MessageDirection(IntegerChoices):
    INBOUND = 0
    OUTBOUND = 1

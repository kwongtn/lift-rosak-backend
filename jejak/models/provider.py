from django.db import models

from jejak.models.abstracts import IdentifierDetailAbstractModel, RangeAbstractModel


class Provider(IdentifierDetailAbstractModel):
    captains = models.ManyToManyField(
        to="jejak.Captain",
        through="jejak.CaptainProviderRange",
    )


class BusProviderRange(RangeAbstractModel):
    pass

from django.db import models

from jejak.models.abstracts import IdentifierDetailAbstractModel, RangeAbstractModel


class Captain(IdentifierDetailAbstractModel):
    providers = models.ManyToManyField(
        to="jejak.Provider",
        through="jejak.CaptainProviderRange",
    )


class CaptainProviderRange(RangeAbstractModel):
    captain = models.ForeignKey(
        "jejak.Captain",
        on_delete=models.PROTECT,
    )
    provider = models.ForeignKey(
        "jejak.Provider",
        on_delete=models.PROTECT,
    )


class CaptainBusRange(RangeAbstractModel):
    captain = models.ForeignKey(
        "jejak.Captain",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )

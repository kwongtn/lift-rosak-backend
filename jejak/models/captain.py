from django.db import models

from jejak.models.abstracts import IdentifierDetailAbstractModel, RangeAbstractModel


class Captain(IdentifierDetailAbstractModel):
    pass


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

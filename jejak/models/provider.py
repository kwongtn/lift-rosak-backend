from django.contrib.postgres.indexes import GistIndex
from django.db import models

from jejak.models.abstracts import IdentifierDetailAbstractModel, RangeAbstractModel


class Provider(IdentifierDetailAbstractModel):
    captains = models.ManyToManyField(
        to="jejak.Captain",
        through="jejak.CaptainProviderRange",
    )


class BusProviderRange(RangeAbstractModel):
    bus = models.ForeignKey(
        to="jejak.Bus",
        on_delete=models.PROTECT,
    )
    provider = models.ForeignKey(
        to="jejak.Provider",
        on_delete=models.PROTECT,
    )

    class Meta:
        indexes = [
            GistIndex(
                fields=["bus", "dt_range"],
                name="idx_busproviderrange_bus_range",
            )
        ]

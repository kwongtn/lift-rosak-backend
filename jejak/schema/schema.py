from typing import List

from strawberry_django_plus import gql

from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import BusOrder, LocationOrder
from jejak.schema.scalars import Bus, Location


@gql.type
class JejakScalars:
    locations: List[Location] = gql.django.field(
        filters=LocationFilter,
        order=LocationOrder,
        pagination=True,
    )
    buses: List[Bus] = gql.django.field(
        pagination=True,
        order=BusOrder,
    )


@gql.type
class JejakMutations:
    pass

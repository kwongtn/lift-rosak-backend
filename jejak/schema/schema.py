from typing import List

from strawberry_django_plus import gql

from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import LocationOrder
from jejak.schema.scalars import Location


@gql.type
class JejakScalars:
    locations: List[Location] = gql.django.field(
        filters=LocationFilter,
        order=LocationOrder,
        pagination=True,
    )


@gql.type
class JejakMutations:
    pass

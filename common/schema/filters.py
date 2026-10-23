from datetime import MAXYEAR, MINYEAR

import strawberry_django
from django.db.models import Q
from graphql import GraphQLError

from common import models


@strawberry_django.filter_type(models.Media)
class MediaFilter:
    @strawberry_django.filter_field
    def created_year(self, value: int, prefix: str) -> Q:
        if not MINYEAR <= value <= MAXYEAR:
            raise GraphQLError(
                f"createdYear must be a year from {MINYEAR} to {MAXYEAR}."
            )

        # `created` is a naive local datetime (USE_TZ = False), so this is the local
        # calendar year, the one `mediasGroupByPeriod` counts. Django turns `__year`
        # into a BETWEEN range, which an index on `created` can serve.
        return Q(**{f"{prefix}created__year": value})


# @strawberry_django.filters.filter(models.User)
# class UserFilter:
#     firebase_id: str

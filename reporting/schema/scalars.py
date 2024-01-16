from typing import List

import strawberry
import strawberry_django

from operation.schema.scalars import Asset
from reporting import models


@strawberry_django.type(models.Report)
class Report:
    id: str
    asset: "Asset"
    # reporter: "User"
    description: str
    type: strawberry.auto


@strawberry_django.type(models.Resolution)
class Resolution:
    id: str
    reports: List["Report"]
    # user: "User"
    notes: str


@strawberry_django.type(models.Vote)
class Vote:
    id: strawberry.auto
    is_upvote: bool
    report: "Report"
    # user: "User"

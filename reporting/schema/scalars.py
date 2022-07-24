from typing import List

from strawberry_django_plus import gql

from operation.schema.scalars import Asset
from reporting import models


@gql.django.type(models.Report)
class Report:
    id: str
    asset: "Asset"
    # reporter: "User"
    description: str
    type: gql.auto


@gql.django.type(models.Resolution)
class Resolution:
    id: str
    reports: List["Report"]
    # user: "User"
    notes: str


@gql.django.type(models.Vote)
class Vote:
    id: gql.auto
    is_upvote: bool
    report: "Report"
    # user: "User"

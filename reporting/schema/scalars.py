from typing import List

import strawberry
import strawberry.django
from strawberry import auto

from operation.schema.scalars import Asset
from reporting import models
from reporting.schema.enums import ReportType


@strawberry.django.type(models.Report)
class Report:
    id: str
    asset: "Asset"
    # reporter: "User"
    description: str
    type: "ReportType"


@strawberry.django.type(models.Resolution)
class Resolution:
    id: str
    reports: List["Report"]
    # user: "User"


@strawberry.django.type(models.Vote)
class Vote:
    id: auto
    is_upvote: bool
    report: "Report"
    # user: "User"

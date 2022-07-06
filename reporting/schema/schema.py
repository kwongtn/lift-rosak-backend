import typing

import strawberry
import strawberry_django

from reporting.schema.filters import ReportFilter, ResolutionFilter, VoteFilter
from reporting.schema.inputs import (
    ReportInput,
    ReportPartialInput,
    ResolutionInput,
    ResolutionPartialInput,
    VoteInput,
)
from reporting.schema.scalars import Report, Resolution, Vote


@strawberry.type
class ReportingScalars:
    reports: typing.List[Report] = strawberry_django.field(filters=ReportFilter)
    resolutions: typing.List[Resolution] = strawberry_django.field(
        filters=ResolutionFilter
    )
    votes: typing.List[Vote] = strawberry_django.field(filters=VoteFilter)


@strawberry.type
class ReportingMutations:
    create_report: Report = strawberry_django.mutations.create(ReportInput)
    create_reports: typing.List[Report] = strawberry_django.mutations.create(
        ReportInput
    )
    update_reports: typing.List[Report] = strawberry_django.mutations.update(
        ReportPartialInput
    )
    delete_reports: typing.List[Report] = strawberry_django.mutations.delete()

    create_resolution: Resolution = strawberry_django.mutations.create(ResolutionInput)
    create_resolutions: typing.List[Resolution] = strawberry_django.mutations.create(
        ResolutionInput
    )
    update_resolutions: typing.List[Resolution] = strawberry_django.mutations.update(
        ResolutionPartialInput
    )
    delete_resolutions: typing.List[Resolution] = strawberry_django.mutations.delete()

    create_vote: Vote = strawberry_django.mutations.create(VoteInput)
    delete_vote: typing.List[Vote] = strawberry_django.mutations.delete()

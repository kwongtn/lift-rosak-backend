import strawberry
from django.conf import settings
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules
from strawberry.extensions.tracing import SentryTracingExtension
from strawberry_django.optimizer import DjangoOptimizerExtension

from common.schema.schema import CommonMutations, CommonScalars
from incident.schema.schema import IncidentMutations, IncidentScalars
from operation.schema.schema import OperationMutations, OperationScalars
from reporting.schema.schema import ReportingMutations, ReportingScalars
from spotting.schema.schema import SpottingMutations, SpottingScalars


@strawberry.type
class Query(
    OperationScalars,
    ReportingScalars,
    CommonScalars,
    SpottingScalars,
    IncidentScalars,
):
    pass


@strawberry.type
class Mutation(
    OperationMutations,
    ReportingMutations,
    CommonMutations,
    SpottingMutations,
    IncidentMutations,
):
    pass


# @strawberry.type
# class Subscription:
#     pass

extensions = [
    SentryTracingExtension,
    DjangoOptimizerExtension,
]

if not settings.DEBUG:
    extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    # subscription=Subscription,
    extensions=extensions,
)

import strawberry
from django.conf import settings
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules
from strawberry_django.optimizer import DjangoOptimizerExtension

from chartography.schema.schema import ChartographyMutations, ChartographyScalars
from common.schema.schema import CommonMutations, CommonScalars
from incident.schema.schema import IncidentMutations, IncidentScalars
from jejak.schema.schema import JejakMutations, JejakScalars
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
    JejakScalars,
    ChartographyScalars,
):
    pass


@strawberry.type
class Mutation(
    OperationMutations,
    ReportingMutations,
    CommonMutations,
    SpottingMutations,
    IncidentMutations,
    JejakMutations,
    ChartographyMutations,
):
    pass


# @strawberry.type
# class Subscription:
#     pass

extensions = [
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

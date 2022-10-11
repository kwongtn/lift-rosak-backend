from django.conf import settings
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules
from strawberry_django_plus import gql
from strawberry_django_plus.optimizer import DjangoOptimizerExtension

from common.schema.schema import CommonMutations, CommonScalars
from incident.schema.schema import IncidentMutations, IncidentScalars
from operation.schema.schema import OperationMutations, OperationScalars
from reporting.schema.schema import ReportingMutations, ReportingScalars
from spotting.schema.schema import SpottingMutations, SpottingScalars


@gql.type
class Query(
    OperationScalars,
    ReportingScalars,
    CommonScalars,
    SpottingScalars,
    IncidentScalars,
):
    pass


@gql.type
class Mutation(
    OperationMutations,
    ReportingMutations,
    CommonMutations,
    SpottingMutations,
    IncidentMutations,
):
    pass


# @gql.type
# class Subscription:
#     pass

extensions = [
    DjangoOptimizerExtension(),
]

if not settings.DEBUG:
    extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

schema = gql.Schema(
    query=Query,
    mutation=Mutation,
    # subscription=Subscription,
    extensions=extensions,
)

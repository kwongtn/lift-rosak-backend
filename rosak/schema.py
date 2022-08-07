from strawberry_django_plus import gql
from strawberry_django_plus.optimizer import DjangoOptimizerExtension

from common.schema.schema import CommonMutations, CommonScalars
from operation.schema.schema import OperationMutations, OperationScalars
from reporting.schema.schema import ReportingMutations, ReportingScalars
from spotting.schema.schema import SpottingMutations, SpottingScalars


@gql.type
class Query(
    OperationScalars,
    ReportingScalars,
    CommonScalars,
    SpottingScalars,
):
    @gql.field
    def hello(self) -> str:
        return "Hello World"


@gql.type
class Mutation(
    OperationMutations,
    ReportingMutations,
    CommonMutations,
    SpottingMutations,
):
    pass


# @gql.type
# class Subscription:
#     pass


schema = gql.Schema(
    query=Query,
    mutation=Mutation,
    # subscription=Subscription,
    extensions=[
        DjangoOptimizerExtension(),
    ],
)

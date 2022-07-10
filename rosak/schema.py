import strawberry
from strawberry_django_plus.optimizer import DjangoOptimizerExtension

from common.schema.schema import CommonMutations, CommonScalars
from operation.schema.schema import OperationMutations, OperationScalars
from reporting.schema.schema import ReportingMutations, ReportingScalars
from spotting.schema.schema import SpottingScalars


@strawberry.type
class Query(
    OperationScalars,
    ReportingScalars,
    CommonScalars,
    SpottingScalars,
):
    @strawberry.field
    def hello(self) -> str:
        return "Hello World"


@strawberry.type
class Mutation(OperationMutations, ReportingMutations, CommonMutations):
    pass


# @strawberry.type
# class Subscription:
#     pass


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    # subscription=Subscription,
    extensions=[
        DjangoOptimizerExtension,
    ],
)

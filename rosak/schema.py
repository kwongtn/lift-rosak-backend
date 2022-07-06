import strawberry
from strawberry_django_plus.optimizer import DjangoOptimizerExtension

from operation.schema.schema import OperationMutations, OperationScalars
from reporting.schema.schema import ReportingMutations, ReportingScalars


@strawberry.type
class Query(
    OperationScalars,
    ReportingScalars,
):
    @strawberry.field
    def hello(self) -> str:
        return "Hello World"


@strawberry.type
class Mutation(
    OperationMutations,
    ReportingMutations,
):
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

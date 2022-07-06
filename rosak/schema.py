import strawberry
from strawberry_django_plus.optimizer import DjangoOptimizerExtension

from operation.schema.schema import OperationMutations, OperationScalars


@strawberry.type
class Query(
    OperationScalars,
):
    @strawberry.field
    def hello(self) -> str:
        return "Hello World"


@strawberry.type
class Mutation(
    OperationMutations,
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

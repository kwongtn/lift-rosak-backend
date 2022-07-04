import strawberry

from operation.schema.schema import OperationScalars


@strawberry.type
class Query(
    OperationScalars,
):
    @strawberry.field
    def hello(self) -> str:
        return "Hello World"


# @strawberry.type
# class Mutation:
#     pass


# @strawberry.type
# class Subscription:
#     pass


schema = strawberry.Schema(
    query=Query,
    # mutation=Mutation,
    # subscription=Subscription,
)

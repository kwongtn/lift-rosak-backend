import strawberry


@strawberry.type
class Query:
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

import strawberry
from strawberry.types.maybe import Maybe


@strawberry.input
class WebLocationInput:
    accuracy: Maybe[float | None] = strawberry.UNSET
    altitude_accuracy: Maybe[float | None] = strawberry.UNSET
    heading: Maybe[float | None] = strawberry.UNSET
    speed: Maybe[float | None] = strawberry.UNSET
    latitude: Maybe[float | None] = strawberry.UNSET
    longitude: Maybe[float | None] = strawberry.UNSET
    altitude: Maybe[float | None] = strawberry.UNSET

from typing import Optional

import strawberry


@strawberry.input
class WebLocationInput:
    accuracy: Optional[float] = strawberry.UNSET
    altitude_accuracy: Optional[float] = strawberry.UNSET
    heading: Optional[float] = strawberry.UNSET
    speed: Optional[float] = strawberry.UNSET
    latitude: Optional[float] = strawberry.UNSET
    longitude: Optional[float] = strawberry.UNSET
    altitude: Optional[float] = strawberry.UNSET

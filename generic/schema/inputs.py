from typing import Optional

import strawberry


@strawberry.input
class WebLocationInput:
    accuracy: Optional[float]
    altitude_accuracy: Optional[float]
    heading: Optional[float]
    speed: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]
    altitude: Optional[float]

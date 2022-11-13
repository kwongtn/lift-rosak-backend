from typing import Optional

from strawberry_django_plus import gql


@gql.input
class WebLocationInput:
    accuracy: Optional[float]
    altitude_accuracy: Optional[float]
    heading: Optional[float]
    speed: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]
    altitude: Optional[float]

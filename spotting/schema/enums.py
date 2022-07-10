from enum import Enum

import strawberry


@strawberry.enum
class SpottingEventType(Enum):
    DEPOT = "DEPOT"
    LOCATION = "LOCATION"
    BETWEEN_STATIONS = "BETWEEN_STATIONS"

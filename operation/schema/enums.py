from enum import Enum

import strawberry


@strawberry.enum
class AssetType(Enum):
    ESCALATOR = "ESCALATOR"
    LIFT = "LIFT"


@strawberry.enum
class VehicleStatus(Enum):
    IN_SERVICE = "IN_SERVICE"
    NOT_SPOTTED = "NOT_SPOTTED"
    DECOMMISSIONED = "DECOMMISSIONED"
    TESTING = "TESTING"
    UNKNOWN = "UNKNOWN"

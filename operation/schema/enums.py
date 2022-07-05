from enum import Enum

import strawberry


@strawberry.enum
class AssetType(Enum):
    ESCALATOR = "ESCALATOR"
    LIFT = "LIFT"

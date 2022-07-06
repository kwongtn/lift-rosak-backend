from enum import Enum

import strawberry


@strawberry.enum
class ReportType(Enum):
    COSMETIC_BREAKDOWN = "COSMETIC_BREAKDOWN"
    FUNCTIONAL_BREAKDOWN = "FUNCTIONAL_BREAKDOWN"
    RESOLUTION = "RESOLUTION"

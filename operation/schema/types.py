from typing import TYPE_CHECKING, Annotated, Optional

import strawberry


@strawberry.type
class LineVehicleSpottingTrend:
    if TYPE_CHECKING:
        from operation.schema.scalars import Vehicle

    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    week: Optional[int]
    count: int
    event_type: Optional[str]
    vehicle: Annotated["Vehicle", strawberry.lazy("operation.schema.scalars")]


@strawberry.type
class VehicleSpottingTrend:
    if TYPE_CHECKING:
        from operation.schema.scalars import Vehicle

    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    week: Optional[int]
    count: int
    event_type: Optional[str]

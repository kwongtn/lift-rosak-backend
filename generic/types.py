from typing import TypedDict


class Point2D(TypedDict):
    x: float
    y: float


class GeometricSearchField(TypedDict):
    radius: float


class Point2D_SearchField(Point2D, GeometricSearchField):
    pass

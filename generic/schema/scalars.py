from typing import NewType, Tuple

import strawberry
from django.contrib.gis.geos import LinearRing, LineString, MultiPoint, Point, Polygon

GeoPoint = strawberry.scalar(
    NewType("GeoPoint", Tuple[float]),
    description="A geographical point that gets 'x, y' or 'x, y, z' as a tuple.",
    parse_value=lambda v: Point(v),
    serialize=lambda v: v.tuple,
)

GeoLineString = strawberry.scalar(
    NewType("GeoLineString", Tuple[GeoPoint]),
    description="A geographical line that gets multiple 'x, y' or 'x, y, z' tuples to form a line.",
    parse_value=lambda v: LineString(v),
    serialize=lambda v: v.tuple,
)

GeoLinearRing = strawberry.scalar(
    NewType("GeoLinearRing", Tuple[GeoPoint]),
    description="""
        A geographical line that gets multiple 'x, y' or 'x, y, z' tuples to form a line.
        It must be a circle. E.g. It maps back to itself.
    """,
    parse_value=lambda v: LinearRing(v),
    serialize=lambda v: v.tuple,
)

GeoPolygon = strawberry.scalar(
    NewType("GeoPolygon", Tuple[GeoLinearRing]),
    description="""
        A geographical object that gets 2 GeoLinearRing objects, as extrenal and internal rings.
    """,
    parse_value=lambda v: Polygon(v),
    serialize=lambda v: v.tuple,
)

GeoMultiPoint = strawberry.scalar(
    NewType("GeoLineString", Tuple[GeoPoint]),
    description="A geographical object that contains multiple GeoPoints.",
    parse_value=lambda v: MultiPoint(*[Point(x) for x in v]),
    serialize=lambda v: v.tuple,
)

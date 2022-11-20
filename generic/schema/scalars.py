from typing import NewType, Optional, Tuple

from django.contrib.gis.geos import LinearRing, LineString, MultiPoint, Point, Polygon
from strawberry_django_plus import gql

GeoPoint = gql.scalar(
    NewType("GeoPoint", Tuple[float]),
    description="A geographical point that gets 'x, y' or 'x, y, z' as a tuple.",
    parse_value=lambda v: Point(v),
    serialize=lambda v: v.tuple,
)

GeoLineString = gql.scalar(
    NewType("GeoLineString", Tuple[GeoPoint]),
    description="A geographical line that gets multiple 'x, y' or 'x, y, z' tuples to form a line.",
    parse_value=lambda v: LineString(v),
    serialize=lambda v: v.tuple,
)

GeoLinearRing = gql.scalar(
    NewType("GeoLinearRing", Tuple[GeoPoint]),
    description="""
        A geographical line that gets multiple 'x, y' or 'x, y, z' tuples to form a line.
        It must be a circle. E.g. It maps back to itself.
    """,
    parse_value=lambda v: LinearRing(v),
    serialize=lambda v: v.tuple,
)

GeoPolygon = gql.scalar(
    NewType("GeoPolygon", Tuple[GeoLinearRing]),
    description="""
        A geographical object that gets 2 GeoLinearRing objects, as extrenal and internal rings.
    """,
    parse_value=lambda v: Polygon(v),
    serialize=lambda v: v.tuple,
)

GeoMultiPoint = gql.scalar(
    NewType("GeoLineString", Tuple[GeoPoint]),
    description="A geographical object that contains multiple GeoPoints.",
    parse_value=lambda v: MultiPoint(*[Point(x) for x in v]),
    serialize=lambda v: v.tuple,
)


class WebLocationParent:
    id: gql.auto
    accuracy: Optional[float]
    altitudeAccuracy: Optional[float]
    heading: Optional[float]
    speed: Optional[float]
    # latitude: Optional[float]
    # longitude: Optional[float]
    location: Optional[GeoPoint]
    altitude: Optional[float]

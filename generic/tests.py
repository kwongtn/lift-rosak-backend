from django.contrib.gis.geos import LineString, Point
from django.test import TestCase

from generic.schema.scalars import GeoLineString, GeoPoint


class GenericPrimitivesTests(TestCase):
    def test_geo_scalar_parsing_and_serialization(self):
        # Point
        pt = GeoPoint._scalar_definition.parse_value((101.6869, 3.1390))
        self.assertIsInstance(pt, Point)
        self.assertAlmostEqual(pt.x, 101.6869)
        self.assertAlmostEqual(pt.y, 3.1390)

        coords = GeoPoint._scalar_definition.serialize(pt)
        self.assertEqual(coords, (101.6869, 3.1390))

        # LineString
        ls = GeoLineString._scalar_definition.parse_value(
            [(101.68, 3.13), (101.69, 3.14)]
        )
        self.assertIsInstance(ls, LineString)
        self.assertEqual(len(ls.coords), 2)

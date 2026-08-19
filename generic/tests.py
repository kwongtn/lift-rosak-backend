from django.contrib.gis.geos import LineString, Point
from django.test import TestCase
from strawberry import UNSET
from strawberry.types.maybe import Some

from generic.schema.inputs import WebLocationInput
from generic.schema.scalars import GeoLineString, GeoPoint
from rosak.tests.test_schema import assert_maybe_field_behavior


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


class TestWebLocationInput(TestCase):
    def test_web_location_input_omitted_fields_are_none(self):
        for field, gql_field in [
            ("accuracy", "accuracy"),
            ("altitude_accuracy", "altitudeAccuracy"),
            ("heading", "heading"),
            ("speed", "speed"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
            ("altitude", "altitude"),
        ]:
            assert_maybe_field_behavior(
                input_class=WebLocationInput,
                field_name=field,
                test_cases=[
                    ({}, UNSET),
                ],
            )

    def test_web_location_input_partial_coordinates_only_lat_lon(self):
        assert_maybe_field_behavior(
            input_class=WebLocationInput,
            field_name="latitude",
            test_cases=[
                ({"latitude": 3.1390, "longitude": 101.6869}, Some(3.1390)),
            ],
        )
        assert_maybe_field_behavior(
            input_class=WebLocationInput,
            field_name="longitude",
            test_cases=[
                ({"latitude": 3.1390, "longitude": 101.6869}, Some(101.6869)),
            ],
        )
        assert_maybe_field_behavior(
            input_class=WebLocationInput,
            field_name="altitude",
            test_cases=[
                ({"latitude": 3.1390, "longitude": 101.6869}, UNSET),
            ],
        )

    def test_web_location_input_explicit_null_on_optional_fields(self):
        for field, gql_field in [
            ("accuracy", "accuracy"),
            ("altitude_accuracy", "altitudeAccuracy"),
            ("heading", "heading"),
            ("speed", "speed"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
            ("altitude", "altitude"),
        ]:
            assert_maybe_field_behavior(
                input_class=WebLocationInput,
                field_name=field,
                test_cases=[
                    ({gql_field: None}, Some(None)),
                ],
            )

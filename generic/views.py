from django import forms
from django.contrib.gis.geos import Point


class GeometricForm(forms.ModelForm):
    """
    A form class that changes map djang-admin to latitute and longitude fields.

    For inherited classes, override the following fields:
    - field_name                    : The name of the geographical field
    - GeometricForm.Meta.model      : The model to target the field
    - GeometricForm.Meta.widgets    : Not sure what this does, but use the field_name

    Sample:
    class StationForm(GeometricForm):
        field_name = "location"
        GeometricForm.Meta.model = Station
        GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}
    """

    required: bool = None

    latitude = forms.FloatField(
        min_value=-90,
        max_value=90,
        required=required,
    )
    longitude = forms.FloatField(
        min_value=-180,
        max_value=180,
        required=required,
    )

    field_name: str = None

    class Meta:
        exclude = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        coordinates = self.initial.get(self.field_name, None)
        if isinstance(coordinates, Point):
            self.initial["longitude"], self.initial["latitude"] = coordinates.tuple

    def clean(self):
        data = super().clean()
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        point = data.get(self.field_name)
        if latitude and longitude and not point:
            data[self.field_name] = Point(longitude, latitude)
        return data

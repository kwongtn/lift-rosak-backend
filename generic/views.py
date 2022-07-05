# from django.shortcuts import render

# # Create your views here.
# from django import forms
# from django.contrib.gis.geos import Point

# from operation.models import Station


# class GeometricForm(forms.ModelForm):
#     latitude = forms.FloatField(
#         min_value=-90,
#         max_value=90,
#         required=True,
#     )
#     longitude = forms.FloatField(
#         min_value=-180,
#         max_value=180,
#         required=True,
#     )

#     field_name: str = None

#     class Meta(object):
#         model = Station
#         exclude = []
#         widgets = {"location": forms.HiddenInput()}

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         coordinates = self.initial.get(self.field_name, None)
#         if isinstance(coordinates, Point):
#             self.initial["longitude"], self.initial["latitude"] = coordinates.tuple

#     def clean(self):
#         data = super().clean()
#         latitude = data.get("latitude")
#         longitude = data.get("longitude")
#         point = data.get(self.field_name)
#         if latitude and longitude and not point:
#             data[self.field_name] = Point(longitude, latitude)
#         return data

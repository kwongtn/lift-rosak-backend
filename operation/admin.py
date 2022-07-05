from django import forms
from django.contrib.gis import admin

from generic.views import GeometricForm
from operation.models import Asset, AssetMedia, Line, Station, StationLine, StationMedia


class AssetMediaStackedInline(admin.StackedInline):
    model = AssetMedia


class AssetAdmin(admin.ModelAdmin):
    inlines = [AssetMediaStackedInline]


class StationStackedInline(admin.StackedInline):
    model = Station


class StationMediaStackedInline(admin.StackedInline):
    model = StationMedia


class LineStackedInline(admin.StackedInline):
    model = Line


class StationLineStackedInline(admin.StackedInline):
    model = StationLine


class LineAdmin(admin.ModelAdmin):
    inlines = [
        StationLineStackedInline,
    ]


class StationForm(GeometricForm):
    field_name = "location"
    GeometricForm.Meta.model = Station
    GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class StationAdmin(admin.ModelAdmin):
    inlines = [
        StationLineStackedInline,
        StationMediaStackedInline,
    ]
    form = StationForm


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(Asset, AssetAdmin)

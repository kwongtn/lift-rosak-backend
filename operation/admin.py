from django.contrib.gis import admin

from generic.views import GeometricForm
from operation.models import (
    Asset,
    AssetMedia,
    Line,
    Station,
    StationLine,
    StationMedia,
    Vehicle,
    VehicleType,
)


class AssetStackedInline(admin.StackedInline):
    model = Asset
    classes = ["collapse"]


class AssetTabularInline(admin.TabularInline):
    model = Asset
    classes = ["collapse"]


class VehicleTabularInline(admin.TabularInline):
    model = Vehicle


class AssetMediaStackedInline(admin.StackedInline):
    model = AssetMedia
    classes = ["collapse"]


class AssetMediaTabluarInline(admin.TabularInline):
    model = AssetMedia


class AssetAdmin(admin.ModelAdmin):
    inlines = [AssetMediaTabluarInline]
    list_display = [
        "__str__",
        "station",
        "short_description",
        "asset_type",
        "status",
    ]
    list_filter = [
        "asset_type",
        "status",
    ]
    search_fields = [
        "short_description",
        "long_description",
    ]


class StationStackedInline(admin.StackedInline):
    model = Station
    classes = ["collapse"]


class StationMediaStackedInline(admin.StackedInline):
    model = StationMedia
    classes = ["collapse"]


class LineStackedInline(admin.StackedInline):
    model = Line


class StationLineStackedInline(admin.StackedInline):
    model = StationLine
    classes = ["collapse"]


class StationLineTabularInline(admin.TabularInline):
    model = StationLine
    classes = ["collapse"]


class LineAdmin(admin.ModelAdmin):
    inlines = [
        StationLineTabularInline,
    ]
    list_display = [
        "__str__",
        "code",
        "display_name",
        "display_color",
    ]
    search_fields = [
        "code",
        "display_name",
        "display_color",
    ]


class StationForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = Station
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class StationAdmin(admin.ModelAdmin):
    inlines = [
        StationLineTabularInline,
        StationMediaStackedInline,
        AssetTabularInline,
    ]
    form = StationForm
    list_display = [
        "__str__",
        "display_name",
        "location",
    ]
    search_fields = [
        "display_name",
        "internal_representation",
    ]


class StationLineAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "internal_representation",
        "station",
        "line",
    ]
    list_filter = [
        "line",
    ]
    search_fields = [
        "station__name",
        "display_name",
        "internal_representation",
    ]


class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "vehicle_type",
        "status",
        "in_service_since",
    ]
    list_filter = [
        "vehicle_type",
        "status",
        "in_service_since",
    ]
    search_fields = [
        "identification_no",
        "vehicle_type__internal_name",
        "vehicle_type__display_name",
    ]


class VehicleTypeAdmin(admin.ModelAdmin):
    inlines = [VehicleTabularInline]
    list_display = [
        "__str__",
        "internal_name",
        "display_name",
    ]
    search_fields = [
        "internal_name",
        "display_name",
    ]


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(StationLine, StationLineAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(Vehicle, VehicleAdmin)
admin.site.register(VehicleType, VehicleTypeAdmin)

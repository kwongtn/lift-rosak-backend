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


class AssetTabularInline(admin.TabularInline):
    model = Asset


class AssetMediaStackedInline(admin.StackedInline):
    model = AssetMedia


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


class StationMediaStackedInline(admin.StackedInline):
    model = StationMedia


class LineStackedInline(admin.StackedInline):
    model = Line


class StationLineStackedInline(admin.StackedInline):
    model = StationLine


class StationLineTabularInline(admin.TabularInline):
    model = StationLine


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


class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "vehicle_type",
        "status",
        "in_service_since",
    ]


class VehicleTypeAdmin(admin.ModelAdmin):
    pass


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(StationLine, StationLineAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(Vehicle, VehicleAdmin)
admin.site.register(VehicleType, VehicleTypeAdmin)

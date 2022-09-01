from django.contrib.gis import admin
from ordered_model.admin import OrderedInlineModelAdminMixin

from generic.views import GeometricForm
from incident.admin import StationIncidentInlineAdmin, VehicleIncidentInlineAdmin
from operation.models import (
    Asset,
    AssetMedia,
    Line,
    Station,
    StationLine,
    StationMedia,
    Vehicle,
    VehicleLine,
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


class VehicleLineStackedInline(admin.StackedInline):
    model = VehicleLine
    classes = ["collapse"]


class VehicleLineTabularInline(admin.TabularInline):
    model = VehicleLine
    classes = ["collapse"]


class LineAdmin(admin.ModelAdmin):
    inlines = [
        StationLineTabularInline,
        VehicleLineTabularInline,
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


class StationAdmin(OrderedInlineModelAdminMixin, admin.ModelAdmin):
    inlines = [
        StationLineTabularInline,
        StationMediaStackedInline,
        AssetTabularInline,
        StationIncidentInlineAdmin,
    ]
    form = StationForm
    list_display = [
        "__str__",
        "display_name",
        "location",
    ]
    search_fields = [
        "display_name",
    ]


class StationLineAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "internal_representation",
        "station",
        "line",
        "override_internal_representation_constraint",
    ]
    list_filter = [
        "line",
    ]
    search_fields = [
        "station__display_name",
        "display_name",
        "internal_representation",
    ]
    list_editable = [
        "internal_representation",
        "override_internal_representation_constraint",
    ]


class VehicleAdmin(OrderedInlineModelAdminMixin, admin.ModelAdmin):
    inlines = [VehicleLineTabularInline, VehicleIncidentInlineAdmin]
    list_display = [
        "__str__",
        "identification_no",
        "vehicle_type",
        "status",
        "in_service_since",
    ]
    list_filter = [
        "vehicle_type",
        "status",
        "in_service_since",
        "vehicle_lines__display_name",
    ]
    search_fields = [
        "identification_no",
        "vehicle_type__internal_name",
        "vehicle_type__display_name",
    ]
    list_editable = [
        "identification_no",
        "status",
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


class VehicleLineAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "vehicle",
        "line",
    ]
    list_filter = [
        "line",
    ]


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(StationLine, StationLineAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(Vehicle, VehicleAdmin)
admin.site.register(VehicleType, VehicleTypeAdmin)
admin.site.register(VehicleLine, VehicleLineAdmin)

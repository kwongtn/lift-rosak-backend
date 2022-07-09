from django.contrib.gis import admin

from generic.views import GeometricForm
from operation.models import Asset, AssetMedia, Line, Station, StationLine, StationMedia


class AssetStackedInline(admin.StackedInline):
    model = Asset


class AssetMediaStackedInline(admin.StackedInline):
    model = AssetMedia


class AssetMediaTabluarInline(admin.TabularInline):
    model = AssetMedia


class AssetAdmin(admin.ModelAdmin):
    inlines = [AssetMediaTabluarInline]
    list_display = [
        "id",
        "station",
        "short_description",
        "asset_type",
    ]
    list_filter = [
        "asset_type",
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


class LineAdmin(admin.ModelAdmin):
    inlines = [
        StationLineStackedInline,
    ]
    list_display = [
        "id",
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
        StationLineStackedInline,
        StationMediaStackedInline,
    ]
    form = StationForm
    list_display = [
        "id",
        "display_name",
        "location",
    ]
    search_fields = [
        "display_name",
        "internal_representation",
    ]


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(Asset, AssetAdmin)

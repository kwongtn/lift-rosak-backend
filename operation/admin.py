from django.contrib.gis import admin

# from generic.views import GeometricForm
from operation.models import Asset, AssetMedia, Line, Station, StationLine, StationMedia

# Register your models here.


class AssetMediaStackedInline(admin.StackedInline):
    model = AssetMedia
    # classes = ["collapse"]


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


class StationAdmin(admin.ModelAdmin):
    inlines = [
        StationLineStackedInline,
        StationMediaStackedInline,
    ]


admin.site.register(Line, LineAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(Asset, AssetAdmin)

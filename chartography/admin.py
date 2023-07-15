from datetime import datetime

from django.contrib import admin
from rangefilter.filters import DateRangeFilterBuilder, DateTimeRangeFilterBuilder

from chartography.models import LineVehicleStatusCountHistory, Snapshot, Source


class SourceAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "description",
    ]
    list_filter = [
        "name",
        "description",
    ]


class LineVehicleStatusCountHistoryTabularInline(admin.TabularInline):
    model = LineVehicleStatusCountHistory
    classes = ["collapse"]


class SnapshotAdmin(admin.ModelAdmin):
    inlines = [LineVehicleStatusCountHistoryTabularInline]
    list_display = [
        "__str__",
        "date",
        "source",
    ]
    list_filter = [
        (
            "created",
            DateTimeRangeFilterBuilder(
                title="Created",
                default_start=datetime(2020, 1, 1),
                default_end=datetime(2030, 1, 1),
            ),
        ),
        (
            "date",
            DateRangeFilterBuilder(
                title="Spotting Date",
                default_start=datetime(2020, 1, 1),
                default_end=datetime(2030, 1, 1),
            ),
        ),
        "source",
    ]


class LineVehicleStatusCountHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "snapshot",
        "line",
        "status",
        "count",
    ]
    list_filter = [
        "snapshot",
        "line",
        "status",
    ]


admin.site.register(Source, SourceAdmin)
admin.site.register(Snapshot, SnapshotAdmin)
admin.site.register(LineVehicleStatusCountHistory, LineVehicleStatusCountHistoryAdmin)

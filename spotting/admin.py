from datetime import datetime

from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin
from django.db import models
from django.forms import Textarea, TextInput
from ordered_model.admin import OrderedTabularInline
from rangefilter.filters import DateRangeFilterBuilder, DateTimeRangeFilterBuilder

from generic.views import GeometricForm
from spotting.models import Event, LocationEvent
from telegram_provider.models import TelegramSpottingEventLog


class LocationEventForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = LocationEvent
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class TelegramSpottingEventLogInlineAdmin(OrderedTabularInline):
    model = TelegramSpottingEventLog
    readonly_fields = ("move_up_down_links",)
    extra = 0
    fields = (
        "telegram_log",
        "spotting_event",
    )


class EventAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    formfield_overrides = {
        models.CharField: {"widget": TextInput(attrs={"size": "20"})},
        models.TextField: {"widget": Textarea(attrs={"rows": 1, "cols": 20})},
    }
    list_display = [
        "id",
        "reporter",
        "spotting_date",
        "vehicle",
        "status",
        "wheel_status",
        "type",
        "media_count",
        "origin_station",
        "destination_station",
        "is_anonymous",
        "run_number",
        "get_notes",
        "notes",
    ]
    inlines = (TelegramSpottingEventLogInlineAdmin,)
    list_filter = [
        (
            "spotting_date",
            DateRangeFilterBuilder(
                title="Spotting Date",
                default_start=datetime(2020, 1, 1),
                default_end=datetime(2030, 1, 1),
            ),
        ),
        (
            "created",
            DateTimeRangeFilterBuilder(
                title="Created",
                default_start=datetime(2020, 1, 1),
                default_end=datetime(2030, 1, 1),
            ),
        ),
        # (
        #     "modified",
        #     DateTimeRangeFilterBuilder(
        #         title="Modified",
        #         default_start=datetime(2020, 1, 1),
        #         default_end=datetime(2030, 1, 1),
        #     ),
        # ),
        "type",
        "status",
        "is_anonymous",
        "reporter",
        "spotting_date",
    ]
    search_fields = [
        "vehicle__identification_no",
        "vehicle__vehicle_type__internal_name",
        "vehicle__vehicle_type__display_name",
        "origin_station__display_name",
        "destination_station__display_name",
        "spotting_date",
    ]
    list_editable = [
        "run_number",
        "notes",
    ]
    readonly_fields = ("images_widget",)
    date_hierarchy = "created"

    advanced_filter_fields = [
        "reporter",
        "spotting_date",
        "vehicle",
        "status",
        "wheel_status",
        "type",
        "origin_station",
        "destination_station",
        "is_anonymous",
    ]
    autocomplete_fields = (
        # "vehicle",
        "origin_station",
        "destination_station",
    )

    @admin.display(description="Notes")
    def get_notes(self, obj):
        if len(obj.notes) > 32:
            return obj.notes[:29] + "..."
        else:
            return obj.notes

    def media_count(self, obj):
        return obj.medias.count()


class LocationEventAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    form = LocationEventForm
    list_display = [
        "id",
        "location",
        "accuracy",
        "altitude",
        "altitude_accuracy",
        "heading",
        "speed",
    ]
    search_fields = [
        "location",
    ]
    advanced_filter_fields = [
        "location",
        "accuracy",
        "altitude",
        "altitude_accuracy",
        "heading",
        "speed",
    ]
    autocomplete_fields = ("event",)


admin.site.register(Event, EventAdmin)
admin.site.register(LocationEvent, LocationEventAdmin)

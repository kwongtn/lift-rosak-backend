from datetime import datetime

from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin
from django.db import models
from django.forms import Textarea, TextInput
from rangefilter.filters import DateRangeFilterBuilder, DateTimeRangeFilterBuilder

from generic.views import GeometricForm
from spotting.models import Event, LocationEvent


class LocationEventForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = LocationEvent
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


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
        "type",
        "origin_station",
        "destination_station",
        "is_anonymous",
        "run_number",
        "notes",
    ]
    list_filter = [
        (
            "spotting_date",
            DateRangeFilterBuilder(
                title="Created",
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

    advanced_filter_fields = [
        "reporter",
        "spotting_date",
        "vehicle",
        "status",
        "type",
        "origin_station",
        "destination_station",
        "is_anonymous",
    ]


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


admin.site.register(Event, EventAdmin)
admin.site.register(LocationEvent, LocationEventAdmin)

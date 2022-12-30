from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin

from generic.views import GeometricForm
from spotting.models import Event, LocationEvent


class LocationEventForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = LocationEvent
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class EventAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
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
    ]
    list_filter = [
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
        "status",
        "type",
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

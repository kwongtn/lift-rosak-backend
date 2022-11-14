from django.contrib import admin

from generic.views import GeometricForm
from spotting.models import Event, LocationEvent


class LocationEventForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = LocationEvent
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class EventAdmin(admin.ModelAdmin):
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
    ]
    search_fields = [
        "vehicle__identification_no",
        "vehicle__vehicle_type__internal_name",
        "vehicle__vehicle_type__display_name",
        "origin_station__display_name",
        "destination_station__display_name",
    ]
    list_editable = [
        "spotting_date",
        "status",
        "type",
    ]


class LocationEventAdmin(admin.ModelAdmin):
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


admin.site.register(Event, EventAdmin)
admin.site.register(LocationEvent, LocationEventAdmin)

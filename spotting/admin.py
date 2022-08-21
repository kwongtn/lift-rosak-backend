from django.contrib import admin

from generic.views import GeometricForm
from spotting.models import Event


class EventForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = Event
    # GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class EventAdmin(admin.ModelAdmin):
    form = EventForm
    list_display = [
        "id",
        "reporter",
        "spotting_date",
        "vehicle",
        "status",
        "type",
        "origin_station",
        "destination_station",
        "location",
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


admin.site.register(Event, EventAdmin)

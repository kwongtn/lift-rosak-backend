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
        "vehicle",
        "status",
        "type",
        "origin_station",
        "destination_station",
        "location",
    ]
    list_filter = [
        "type",
        "vehicle",
        "reporter",
        "status",
        "origin_station",
        "destination_station",
    ]


admin.site.register(Event, EventAdmin)

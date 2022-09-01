from django.contrib.gis import admin, forms
from ordered_model.admin import OrderedModelAdmin, OrderedTabularInline

from generic.views import GeometricForm
from incident.models import StationIncident, VehicleIncident

incident_list_display = [
    "__str__",
    "severity",
    "title",
    "move_up_down_links",
    "order",
    "is_last",
]

incident_list_filter = ["severity", "is_last"]

incident_list_editable = [
    "title",
    "order",
    "is_last",
]


class VehicleIncidentLocationForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = VehicleIncident
    GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class VehicleIncidentAdmin(OrderedModelAdmin):
    form = VehicleIncidentLocationForm
    list_display = incident_list_display + ["vehicle"]
    list_filter = incident_list_filter + ["vehicle", "vehicle__lines"]
    list_editable = incident_list_editable + ["vehicle"]
    search_fields = [
        "vehicle__identification_no",
    ]


class VehicleIncidentInlineAdmin(OrderedTabularInline):
    form = VehicleIncidentLocationForm
    model = VehicleIncident
    classes = ["collapse"]
    readonly_fields = ("move_up_down_links",)
    ordering = ("order",)
    extra = 1


class StationIncidentLocationForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = StationIncident
    GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class StationIncidentAdmin(OrderedModelAdmin):
    form = StationIncidentLocationForm
    list_display = incident_list_display + ["station"]
    list_filter = incident_list_filter + ["station", "station__lines"]
    list_editable = incident_list_editable + ["station"]


class StationIncidentInlineAdmin(OrderedTabularInline):
    form = StationIncidentLocationForm
    model = StationIncident
    classes = ["collapse"]
    readonly_fields = ("move_up_down_links",)
    ordering = ("order",)
    extra = 1


admin.site.register(VehicleIncident, VehicleIncidentAdmin)
admin.site.register(StationIncident, StationIncidentAdmin)

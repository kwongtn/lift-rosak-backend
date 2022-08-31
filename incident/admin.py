from django.contrib.gis import admin, forms

from generic.views import GeometricForm
from incident.models import StationIncident, VehicleIncident

incident_list_display = [
    "__str__",
    "severity",
    "title",
]

incident_list_filter = ["severity"]


class VehicleIncidentLocationForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = VehicleIncident
    GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class VehicleIncidentAdmin(admin.ModelAdmin):
    form = VehicleIncidentLocationForm
    list_display = incident_list_display + ["vehicle"]
    list_filter = incident_list_filter + ["vehicle"]


class StationIncidentLocationForm(GeometricForm):
    field_name = "location"
    required = False
    GeometricForm.Meta.model = StationIncident
    GeometricForm.Meta.widgets = {field_name: forms.HiddenInput()}


class StationIncidentAdmin(admin.ModelAdmin):
    form = StationIncidentLocationForm
    list_display = incident_list_display + ["station"]
    list_filter = incident_list_filter + ["station"]


admin.site.register(VehicleIncident, VehicleIncidentAdmin)
admin.site.register(StationIncident, StationIncidentAdmin)

from django.contrib.gis import admin

from incident.models import StationIncident, VehicleIncident

incident_list_display = [
    "__str__",
    "severity",
    "title",
]

incident_list_filter = ["severity"]


class VehicleIncidentAdmin(admin.ModelAdmin):
    list_display = incident_list_display + ["vehicle"]
    list_filter = incident_list_filter + ["vehicle"]


class StationIncidentAdmin(admin.ModelAdmin):
    list_display = incident_list_display + ["station"]
    list_filter = incident_list_filter + ["station"]


admin.site.register(VehicleIncident, VehicleIncidentAdmin)
admin.site.register(StationIncident, StationIncidentAdmin)

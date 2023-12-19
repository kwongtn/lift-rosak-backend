from django.contrib.admin import SimpleListFilter
from django.contrib.gis import admin, forms
from django.db import models
from django.forms import Textarea, TextInput
from mdeditor.widgets import MDEditorWidget
from ordered_model.admin import (
    OrderedInlineModelAdminMixin,
    OrderedModelAdmin,
    OrderedTabularInline,
)

from generic.views import GeometricForm
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentChronology,
    StationIncident,
    VehicleIncident,
)
from operation.models import Line

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
    list_editable = incident_list_editable
    search_fields = [
        "vehicle__identification_no",
    ]
    autocomplete_fields = ("vehicle",)


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


class CalendarIncidentChronologyInlineAdmin(OrderedTabularInline):
    model = CalendarIncidentChronology
    readonly_fields = ("move_up_down_links",)
    ordering = ("order",)
    extra = 1
    fields = (
        "order",
        "indicator",
        "datetime",
        "source_url",
        "content",
        "move_up_down_links",
    )

    formfield_overrides = {
        models.URLField: {"widget": TextInput(attrs={"size": 20})},
        models.TextField: {"widget": Textarea(attrs={"rows": 4, "cols": 40})},
    }


class CalendarIncidentAdminForm(forms.ModelForm):
    class Meta:
        model = CalendarIncident
        widgets = {
            "details": MDEditorWidget(),
        }
        fields = "__all__"


class CalendarIncidentLineFilter(SimpleListFilter):
    title = "Line"
    parameter_name = "lines"

    def lookups(self, request, model_admin):
        return [(line.id, line.__str__()) for line in Line.objects.all()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(lines=self.value())


class CalendarIncidentAdmin(OrderedInlineModelAdminMixin, OrderedModelAdmin):
    form = CalendarIncidentAdminForm
    list_display = [
        "__str__",
        "start_datetime",
        "end_datetime",
        "severity",
    ]
    list_filter = (
        "severity",
        CalendarIncidentLineFilter,
    )
    filter_horizontal = (
        "lines",
        "vehicles",
        "stations",
        "categories",
        # "medias",
    )
    ordering = ("-start_datetime",)
    inlines = [
        CalendarIncidentChronologyInlineAdmin,
    ]
    search_fields = (
        "id",
        "title",
        "brief",
        "details",
    )


class CalendarIncidentChronologyAdmin(OrderedModelAdmin):
    list_display = [
        "__str__",
        "indicator",
        "datetime",
        "content",
        "move_up_down_links",
        "order",
    ]
    list_filter = [
        "indicator",
        "datetime",
    ]
    ordering = (
        "calendar_incident",
        "-datetime",
    )
    autocomplete_fields = ("calendar_incident",)


class CalendarIncidentCategoryAdmin(OrderedModelAdmin):
    list_display = [
        "__str__",
        "name",
    ]
    ordering = (
        "id",
        "name",
    )
    search_fields = (
        "id",
        "name",
    )


admin.site.register(VehicleIncident, VehicleIncidentAdmin)
admin.site.register(StationIncident, StationIncidentAdmin)
admin.site.register(CalendarIncident, CalendarIncidentAdmin)
admin.site.register(CalendarIncidentChronology, CalendarIncidentChronologyAdmin)
admin.site.register(CalendarIncidentCategory, CalendarIncidentCategoryAdmin)

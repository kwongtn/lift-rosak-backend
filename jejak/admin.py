from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin
from django.core.paginator import Paginator

from jejak.models import Bus, BusType, Location


class LocationPaginator(Paginator):
    # Used to speed up entry display at cost of inaccurate pagination
    @property
    def count(self):
        return 50000000


class LocationAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    show_full_result_count = False
    paginator = LocationPaginator
    list_display = [
        "id",
        "dt_received",
        "dt_gps",
        "location",
        "dir",
        "speed",
        "angle",
        "bus",
    ]
    search_fields = [
        "bus__identifier",
    ]
    # advanced_filter_fields = [
    #     "code",
    #     "display_name",
    #     "display_color",
    # ]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BusAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    list_display = ["id", "identifier", "type"]


class BusTypeAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    list_display = ["id", "title", "description"]


admin.site.register(Location, LocationAdmin)
admin.site.register(Bus, BusAdmin)
admin.site.register(BusType, BusTypeAdmin)

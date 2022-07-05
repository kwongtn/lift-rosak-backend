import strawberry
import strawberry_django

from operation import models
from operation.enums import AssetType


@strawberry_django.filters.filter(models.Line)
class LineFilter:
    id: strawberry.ID
    code: str
    display_name: str
    display_color: str

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_code(self, queryset):
        return queryset.filter(code__icontains=self.code)

    def filter_display_name(self, queryset):
        return queryset.filter(display_name__icontains=self.display_name)

    def filter_display_color(self, queryset):
        return queryset.filter(display_color__icontains=self.display_color)


@strawberry_django.filters.filter(models.Asset)
class AssetFilter:
    id: strawberry.ID
    officialid: str
    asset_type: "AssetType"

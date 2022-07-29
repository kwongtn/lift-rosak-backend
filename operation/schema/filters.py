from strawberry_django_plus import gql

from operation import models

# from django.contrib.gis.geos import Point
# from django.contrib.gis.measure import Distance


# from operation.schema.enums import AssetType


@gql.django.filters.filter(models.Line)
class LineFilter:
    id: gql.ID
    code: str
    display_name: str
    display_color: str
    first_only: bool

    def filter_first_only(self, queryset):
        if self.first_only:
            return queryset[:1]
        else:
            return queryset

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_code(self, queryset):
        return queryset.filter(code__icontains=self.code)

    def filter_display_name(self, queryset):
        return queryset.filter(display_name__icontains=self.display_name)

    def filter_display_color(self, queryset):
        return queryset.filter(display_color__icontains=self.display_color)


# @strawberry_django.filters.filter(models.Asset)
# class AssetFilter:
#     id: strawberry.ID
#     officialid: str
#     asset_type: AssetType
#     station_id: strawberry.ID

#     def filter_id(self, queryset):
#         return queryset.filter(id=self.id)

#     def filter_officialid(self, queryset):
#         return queryset.filter(officialid=self.officialid)

#     def filter_asset_type(self, queryset):
#         return queryset.filter(asset_type=self.asset_type)

#     def filter_station_id(self, queryset):
#         return queryset.filter(station_id=self.station_id)


# @strawberry_django.filters.filter(models.Station)
# class StationFilter:
#     id: strawberry.ID
#     display_name: str
#     internal_representation: str
#     location: strawberry.scalars.JSON

#     def filter_id(self, queryset):
#         return queryset.filter(id=self.id)

#     def filter_display_name(self, queryset):
#         return queryset.filter(display_name__icontains=self.display_name)

#     def filter_internal_representation(self, queryset):
#         return queryset.filter(internal_representation=self.internal_representation)

#     def filter_location(self, queryset):
#         return queryset.filter(
#             location__distance_lt=(
#                 Point(
#                     self.location.get("x"),
#                     self.location.get("y"),
#                     self.location.get("z"),
#                 ),
#                 Distance(km=self.location.get("radius")),
#             )
#         )

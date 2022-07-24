# from typing import List

# import strawberry
# import strawberry_django

# from generic.schema.scalars import GeoPoint
# from operation import models
# from operation.schema.enums import AssetType


# @strawberry_django.input(models.Line)
# class LineInput:
#     code: str
#     display_name: str
#     display_color: str
#     stations: List[int]


# @strawberry_django.input(models.Line, partial=True)
# class LinePartialInput(LineInput):
#     id: strawberry.auto


# @strawberry_django.input(models.Asset)
# class AssetInput:
#     officialid: str
#     station_id: strawberry.ID
#     short_description: str
#     long_description: str
#     asset_type: AssetType
#     # medias: List[Media]


# @strawberry_django.input(models.Asset, partial=True)
# class AssetPartialInput(AssetInput):
#     id: strawberry.ID


# @strawberry_django.input(models.Station)
# class StationInput:
#     display_name: str
#     internal_representation: str
#     location: GeoPoint
#     # lines: List[Line]
#     # medias: List[Media]


# @strawberry_django.input(models.Station, partial=True)
# class StationPartialInput(StationInput):
#     id: strawberry.ID

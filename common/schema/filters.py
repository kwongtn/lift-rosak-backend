import strawberry
import strawberry_django

from common.schema import models


@strawberry_django.filters.filter(models.Media)
class MediaFilter:
    id: str
    uploader_id: strawberry.ID

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_uploader_id(self, queryset):
        return queryset.filter(uploader_id=self.uploader_id)


@strawberry_django.filters.filter(models.User)
class UserFilter:
    id: strawberry.ID
    firebase_id: str

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_firebase_id(self, queryset):
        return queryset.filter(firebase_id=self.firebase_id)

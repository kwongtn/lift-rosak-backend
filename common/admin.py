from django.contrib import admin

from common.models import Media, User
from mlptf.admin import UserBadgeStackedInline


class MediaStackedInline(admin.StackedInline):
    model = Media


class MediaTabularInline(admin.TabularInline):
    model = Media


class UserStackedInline(admin.StackedInline):
    model = User


class MediaAdmin(admin.ModelAdmin):
    fields = [
        "id",
        "created",
        "modified",
        "file",
        "image_widget",
        "uploader",
    ]
    readonly_fields = [
        "id",
        "created",
        "modified",
        "image_widget",
    ]
    list_display = [
        "__str__",
        "uploader",
    ]
    list_filter = [
        "uploader",
    ]
    search_fields = [
        "uploader",
    ]


class UserAdmin(admin.ModelAdmin):
    inlines = [UserBadgeStackedInline]
    list_display = [
        "__str__",
        "nickname",
        "firebase_id",
    ]
    search_fields = [
        "nickname",
        "firebase_id",
    ]


admin.site.register(Media, MediaAdmin)
admin.site.register(User, UserAdmin)

from django.contrib import admin

from common.models import Media, TemporaryMedia, User
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
        "width_x_height",
        "image_widget",
        "uploader",
    ]
    readonly_fields = [
        "id",
        "created",
        "modified",
        "width_x_height",
        "image_widget",
    ]
    list_display = [
        "__str__",
        "created",
        "width_x_height",
        "uploader",
    ]
    list_filter = [
        "uploader",
    ]
    search_fields = [
        "uploader",
    ]

    def width_x_height(self, instance):
        return f"{instance.width} x {instance.height}"


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
admin.site.register(TemporaryMedia, MediaAdmin)
admin.site.register(User, UserAdmin)

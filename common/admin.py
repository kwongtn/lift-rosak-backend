from django.contrib import admin

from common.models import Media, User
from mlptf.admin import UserBadgeStackedInline


class MediaStackedInline(admin.StackedInline):
    model = Media


class MediaTabularInline(admin.TabularInline):
    model = Media


class UserStackedInline(admin.StackedInline):
    model = User


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


admin.site.register(Media, admin.ModelAdmin)
admin.site.register(User, UserAdmin)

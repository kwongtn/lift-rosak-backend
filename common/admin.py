from django.contrib import admin

from common.models import Media, User
from reporting.admin import ReportStackedInline, VoteTabularInline


class MediaStackedInline(admin.StackedInline):
    model = Media


class MediaTabularInline(admin.TabularInline):
    model = Media


class UserAdmin(admin.ModelAdmin):
    inlines = [
        VoteTabularInline,
        ReportStackedInline,
        MediaStackedInline,
    ]
    list_display = [
        "__str__",
        "firebase_id",
    ]
    search_fields = [
        "firebase_id",
    ]


admin.site.register(Media, admin.ModelAdmin)
admin.site.register(User, UserAdmin)

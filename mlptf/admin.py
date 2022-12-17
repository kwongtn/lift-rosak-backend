from django.contrib import admin

from mlptf.models import Badge, UserBadge


class UserBadgeStackedInline(admin.StackedInline):
    model = UserBadge
    classes = ["collapse"]


class BadgeAdmin(admin.ModelAdmin):
    inlines = [UserBadgeStackedInline]
    list_display = [
        "id",
        "name",
        "released",
    ]
    search_fields = [
        "name",
        "released",
    ]


admin.site.register(Badge, BadgeAdmin)

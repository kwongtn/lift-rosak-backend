from django.contrib import admin

from common.models import Media, User, UserJejakTransaction
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
        "firebase_id",
    ]
    search_fields = [
        "firebase_id",
    ]
    readonly_fields = [
        "credit_balance",
        "free_credit_balance",
        "non_free_credit_balance",
    ]


class UserJejakTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "created",
        "category",
        "user",
        "credit_change",
    ]
    search_fields = [
        "user__firebase_id",
        "details",
    ]
    list_filter = [
        "user",
        "category",
    ]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Media, admin.ModelAdmin)
admin.site.register(User, UserAdmin)
admin.site.register(UserJejakTransaction, UserJejakTransactionAdmin)

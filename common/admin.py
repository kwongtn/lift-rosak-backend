from django.contrib import admin

from common.models import (
    Clearance,
    FeatureFlag,
    Media,
    TemporaryMedia,
    User,
    UserClearance,
    UserJejakTransaction,
)
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


class TemporaryMediaAdmin(admin.ModelAdmin):
    fields = (
        "id",
        "created",
        "modified",
        "file",
        "image_widget",
        "uploader",
        "status",
        "prettified_metadata",
        "fail_count",
    )

    readonly_fields = [
        "id",
        "created",
        "modified",
        "image_widget",
        "uploader",
        "prettified_metadata",
        "fail_count",
    ]
    list_display = [
        "id",
        "created",
        "uploader",
        "status",
        "fail_count",
    ]
    list_filter = [
        "uploader",
        "status",
        "fail_count",
    ]
    search_fields = [
        "uploader",
    ]

    def prettified_metadata(self, instance):
        self.prettify_json(instance.metadata)


class UserClearanceStackedInline(admin.StackedInline):
    model = UserClearance
    classes = ["collapse"]


class UserAdmin(admin.ModelAdmin):
    inlines = [UserBadgeStackedInline, UserClearanceStackedInline]
    list_display = [
        "__str__",
        "nickname",
        "firebase_id",
    ]
    search_fields = [
        "nickname",
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

    # filter_horizontal = ("clearances",)


class ClearanceAdmin(admin.ModelAdmin):
    pass


class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "enabled",
    ]
    list_editable = [
        "enabled",
    ]


admin.site.register(Media, MediaAdmin)
admin.site.register(TemporaryMedia, TemporaryMediaAdmin)
admin.site.register(User, UserAdmin)
admin.site.register(UserJejakTransaction, UserJejakTransactionAdmin)
admin.site.register(Clearance, ClearanceAdmin)
admin.site.register(FeatureFlag, FeatureFlagAdmin)

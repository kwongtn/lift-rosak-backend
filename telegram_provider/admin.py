from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin

from generic.admin import JsonPrettifyAdminMixin
from telegram_provider.models import TelegramLogs


class TelegramLogAdmin(
    AdminAdvancedFiltersMixin, JsonPrettifyAdminMixin, admin.ModelAdmin
):
    list_display = (
        "__str__",
        "direction",
        "retry_count",
        "last_error",
        "sent_at",
        "created",
        "modified",
    )
    list_filter = ("direction",)

    model = TelegramLogs
    readonly_fields = (
        "prettified_payload",
        "retry_count",
        "last_error",
        "sent_at",
    )

    def prettified_payload(self, instance):
        self.prettify_json(instance.payload)


admin.site.register(TelegramLogs, TelegramLogAdmin)

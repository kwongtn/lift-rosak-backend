from advanced_filters.admin import AdminAdvancedFiltersMixin
from django.contrib import admin

from telegram_provider.models import TelegramLogs


class TelegramLogAdmin(AdminAdvancedFiltersMixin, admin.ModelAdmin):
    model = TelegramLogs
    readonly_fields = ("payload",)


admin.site.register(TelegramLogs, TelegramLogAdmin)

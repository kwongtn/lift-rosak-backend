from django.contrib import admin

from common.models import Media, User


class MediaStackedInline(admin.StackedInline):
    model = Media


admin.site.register(Media, admin.ModelAdmin)
admin.site.register(User, admin.ModelAdmin)

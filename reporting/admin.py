from django.contrib import admin

from reporting.models import Report, ReportResolution, Resolution, Vote


class ReportStackedInline(admin.StackedInline):
    model = Report


class ResolutionStackedInline(admin.StackedInline):
    model = Resolution


class VoteStackedInline(admin.StackedInline):
    model = Vote


class ReportResolutionStackedInline(admin.StackedInline):
    model = ReportResolution


class ReportAdmin(admin.ModelAdmin):
    pass


class ResolutionAdmin(admin.ModelAdmin):
    inlines = [
        ReportResolutionStackedInline,
    ]


class VoteAdmin(admin.ModelAdmin):
    pass


admin.site.register(Report, ReportAdmin)
admin.site.register(Resolution, ResolutionAdmin)
admin.site.register(Vote, VoteAdmin)

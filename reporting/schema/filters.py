from typing import List

import strawberry
import strawberry_django

from reporting import models
from reporting.schema.enums import ReportType


@strawberry_django.filters.filter(models.Report)
class ReportFilter:
    id: str
    asset_ids: List[strawberry.ID]
    reporter_ids: List[strawberry.ID]
    types: List["ReportType"]

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_asset_ids(self, queryset):
        return queryset.filter(asset_id__in=self.asset_ids)

    def filter_reporter_ids(self, queryset):
        return queryset.filter(reporter_id__in=self.reporter_ids)

    def filter_types(self, queryset):
        return queryset.filter(report_type__in=self.types)


@strawberry_django.filters.filter(models.Resolution)
class ResolutionFilter:
    id: str
    # report_id: str
    # user_id: strawberry.ID

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    # def filter_report_id(self, queryset):
    #     return queryset.filter(report_id=self.report_id)


@strawberry_django.filters.filter(models.Vote)
class VoteFilter:
    id: strawberry.ID
    report_id: str
    user_id: strawberry.ID
    is_upvote: bool

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_report_id(self, queryset):
        return queryset.filter(report_id=self.report_id)

    def filter_user_id(self, queryset):
        return queryset.filter(user_id=self.user_id)

    def filter_is_upvote(self, queryset):
        return queryset.filter(is_upvote=self.is_upvote)

# from typing import List

# import strawberry
# import strawberry_django

# from reporting import models
# from reporting.schema.enums import ReportType


# @strawberry_django.input(models.Report)
# class ReportInput:
#     asset_id: strawberry.ID
#     reporter_id: strawberry.ID
#     description: str
#     type: "ReportType"


# @strawberry_django.input(models.Report, partial=True)
# class ReportPartialInput(ReportInput):
#     id: strawberry.ID


# @strawberry_django.input(models.Resolution)
# class ResolutionInput:
#     report_ids: List[str]
#     user_id: strawberry.ID
#     notes: str


# @strawberry_django.input(models.Resolution, partial=True)
# class ResolutionPartialInput(ResolutionInput):
#     id: strawberry.ID


# @strawberry_django.input(models.Vote)
# class VoteInput:
#     report_id: strawberry.ID
#     user_id: strawberry.ID
#     is_upvote: bool

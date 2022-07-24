from strawberry_django_plus import gql


@gql.type
class ReportingScalars:
    # reports: typing.List[Report] = gql.django.field(filters=ReportFilter)
    # resolutions: typing.List[Resolution] = gql.django.field(filters=ResolutionFilter)
    # votes: typing.List[Vote] = gql.django.field(filters=VoteFilter)
    pass


@gql.type
class ReportingMutations:
    # create_report: Report = gql.django.mutations.create(ReportInput)
    # create_reports: typing.List[Report] = gql.django.mutations.create(ReportInput)
    # update_reports: typing.List[Report] = gql.django.mutations.update(
    #     ReportPartialInput
    # )
    # delete_reports: typing.List[Report] = gql.django.mutations.delete()

    # create_resolution: Resolution = gql.django.mutations.create(ResolutionInput)
    # create_resolutions: typing.List[Resolution] = gql.django.mutations.create(
    #     ResolutionInput
    # )
    # update_resolutions: typing.List[Resolution] = gql.django.mutations.update(
    #     ResolutionPartialInput
    # )
    # delete_resolutions: typing.List[Resolution] = gql.django.mutations.delete()

    # create_vote: Vote = gql.django.mutations.create(VoteInput)
    # delete_vote: typing.List[Vote] = gql.django.mutations.delete()
    pass

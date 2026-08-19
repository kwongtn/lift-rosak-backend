import strawberry
from django.apps import apps
from django.conf import settings
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules
from strawberry_django.optimizer import DjangoOptimizerExtension

if apps.is_installed("chartography"):
    from chartography.schema.schema import ChartographyMutations, ChartographyScalars

if apps.is_installed("common"):
    from common.schema.schema import CommonMutations, CommonScalars

if apps.is_installed("incident"):
    from incident.schema.schema import IncidentMutations, IncidentScalars

if apps.is_installed("operation"):
    from operation.schema.schema import OperationMutations, OperationScalars

if apps.is_installed("reporting"):
    from reporting.schema.schema import ReportingMutations, ReportingScalars

if apps.is_installed("spotting"):
    from spotting.schema.schema import SpottingMutations, SpottingScalars

if getattr(settings, "JEJAK_ENABLED", False):
    from jejak.schema.schema import JejakMutations, JejakScalars

query_bases = []
mutation_bases = []

if apps.is_installed("operation"):
    query_bases.append(OperationScalars)
    mutation_bases.append(OperationMutations)

if apps.is_installed("reporting"):
    query_bases.append(ReportingScalars)
    mutation_bases.append(ReportingMutations)

if apps.is_installed("common"):
    query_bases.append(CommonScalars)
    mutation_bases.append(CommonMutations)

if apps.is_installed("spotting"):
    query_bases.append(SpottingScalars)
    mutation_bases.append(SpottingMutations)

if apps.is_installed("incident"):
    query_bases.append(IncidentScalars)
    mutation_bases.append(IncidentMutations)

if apps.is_installed("chartography"):
    query_bases.append(ChartographyScalars)
    mutation_bases.append(ChartographyMutations)

if getattr(settings, "JEJAK_ENABLED", False):
    query_bases.insert(5, JejakScalars)
    mutation_bases.insert(5, JejakMutations)


@strawberry.type
class Query(*query_bases):
    pass


@strawberry.type
class Mutation(*mutation_bases):
    pass


# @strawberry.type
# class Subscription:
#     pass

extensions = [
    DjangoOptimizerExtension,
]

if not settings.DEBUG:
    extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    # subscription=Subscription,
    extensions=extensions,
)

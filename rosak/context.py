import copy
from typing import Any

from django.http import HttpRequest, HttpResponse
from strawberry.django.views import AsyncGraphQLView

from operation.schema.loaders import OperationContextLoaders

# @dataclasses.dataclass
# class ContextLoaders:
#     operation: OperationContextLoaders = dataclasses.field(
#         default_factory=OperationContextLoaders
# )

ContextLoaders = {"operation": copy.deepcopy(OperationContextLoaders)}


class CustomGraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        return {"loaders": copy.deepcopy(ContextLoaders)}

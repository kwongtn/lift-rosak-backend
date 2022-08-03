from typing import Any

from django.http import HttpRequest, HttpResponse
from dotmap import DotMap
from strawberry.django.views import AsyncGraphQLView

from operation.schema.loaders import OperationContextLoaders


class ContextLoaders:
    operation = OperationContextLoaders()


class CustomGraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        return DotMap({"loaders": ContextLoaders()})

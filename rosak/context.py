import copy
from typing import Any

from django.http import HttpRequest, HttpResponse
from dotmap import DotMap
from strawberry.django.views import AsyncGraphQLView

from common.utils import FirebaseUser
from operation.schema.loaders import OperationContextLoaders
from spotting.schema.loaders import SpottingContextLoaders

ContextLoaders = {
    "operation": OperationContextLoaders,
    "spotting": SpottingContextLoaders,
}


class CustomGraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        return DotMap(
            {
                "loaders": copy.deepcopy(ContextLoaders),
                "request": request,
                "response": response,
                "user": await FirebaseUser(request).get_current_user(),
            }
        )

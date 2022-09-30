import copy
from typing import Any

from django.http import HttpRequest, HttpResponse
from dotmap import DotMap
from strawberry.django.views import AsyncGraphQLView

from common.utils import get_user_from_firebase_key
from operation.schema.loaders import OperationContextLoaders

ContextLoaders = {"operation": OperationContextLoaders}


class CustomGraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        return DotMap(
            {
                "loaders": copy.deepcopy(ContextLoaders),
                "request": request,
                "response": response,
                "user": await get_user_from_firebase_key(request),
            }
        )

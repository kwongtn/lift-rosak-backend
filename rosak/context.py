import copy
import json
import math
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from dotmap import DotMap
from graphql.error.graphql_error import format_error as format_graphql_error
from strawberry.django.views import AsyncGraphQLView
from strawberry.http import GraphQLHTTPResponse
from strawberry.types import ExecutionResult

from common.enums import UserJejakTransactionCategory
from common.models import UserJejakTransaction
from common.schema.loaders import CommonContextLoaders
from common.utils import FirebaseUser, get_charge_credits_objs
from operation.schema.loaders import OperationContextLoaders
from spotting.schema.loaders import SpottingContextLoaders

ContextLoaders = {
    "operation": OperationContextLoaders,
    "spotting": SpottingContextLoaders,
    "common": CommonContextLoaders,
}


class CustomGraphQLView(AsyncGraphQLView):
    async def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        self.user = await FirebaseUser(request).get_current_user()

        return DotMap(
            {
                "loaders": copy.deepcopy(ContextLoaders),
                "request": request,
                "response": response,
                "user": self.user,
            }
        )

    async def process_result(
        self, request: HttpRequest, result: ExecutionResult
    ) -> GraphQLHTTPResponse:
        data: GraphQLHTTPResponse = {"data": result.data}

        if result.errors:
            data["errors"] = [format_graphql_error(err) for err in result.errors]

        to_create_list = []
        free_credit_balance_modifier = 0
        if data["data"].get("locationsCount"):
            objs, modifier = await get_charge_credits_objs(
                user=self.user,
                category=UserJejakTransactionCategory.COUNT_ROWS,
                amount=-1 * settings.COUNT_ROWS_MULTIPLIER,
                details=request.body.decode("utf-8"),
                free_credit_balance_modifier=free_credit_balance_modifier,
            )

            to_create_list += objs
            free_credit_balance_modifier += modifier

        if data["data"].get("locations"):
            objs, modifier = await get_charge_credits_objs(
                user=self.user,
                category=UserJejakTransactionCategory.BUS_LOCATION_HISTORY,
                amount=-1
                * math.ceil(
                    len(data["data"].get("locations"))
                    * settings.BUS_LOCATION_HISTORY_MULTIPLIER
                ),
                details=request.body.decode("utf-8"),
                free_credit_balance_modifier=free_credit_balance_modifier,
            )

            to_create_list += objs
            free_credit_balance_modifier += modifier

            objs, modifier = await get_charge_credits_objs(
                user=self.user,
                category=UserJejakTransactionCategory.BANDWIDTH,
                amount=-1
                * math.ceil(
                    len(json.dumps(data["data"])) / 1000 * settings.BANDWIDTH_MULTIPLIER
                ),
                details=request.body.decode("utf-8"),
                free_credit_balance_modifier=free_credit_balance_modifier,
            )

            to_create_list += objs
            free_credit_balance_modifier += modifier

        await UserJejakTransaction.objects.abulk_create(to_create_list)

        return data

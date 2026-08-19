import copy
import json
import math
from typing import Any

from django.conf import settings
from django.db import DatabaseError, OperationalError
from django.http import HttpRequest, HttpResponse
from dotmap import DotMap
from graphql.error.graphql_error import format_error as format_graphql_error
from strawberry.django.views import AsyncGraphQLView
from strawberry.http import GraphQLHTTPResponse
from strawberry.types import ExecutionResult

try:
    from common.enums import UserJejakTransactionCategory
    from common.models import UserJejakTransaction
    from common.schema.loaders import CommonContextLoaders
    from common.utils import FirebaseUser, get_charge_credits_objs
except ImportError:
    UserJejakTransaction = None
    CommonContextLoaders = None
    FirebaseUser = None
    get_charge_credits_objs = None
    UserJejakTransactionCategory = None

try:
    from incident.schema.loaders import IncidentContextLoaders
except ImportError:
    IncidentContextLoaders = None

try:
    from operation.schema.loaders import OperationContextLoaders
except ImportError:
    OperationContextLoaders = None

try:
    from spotting.schema.loaders import SpottingContextLoaders
except ImportError:
    SpottingContextLoaders = None

ContextLoaders = {}
if CommonContextLoaders is not None:
    ContextLoaders["common"] = CommonContextLoaders
if IncidentContextLoaders is not None:
    ContextLoaders["incident"] = IncidentContextLoaders
if OperationContextLoaders is not None:
    ContextLoaders["operation"] = OperationContextLoaders
if SpottingContextLoaders is not None:
    ContextLoaders["spotting"] = SpottingContextLoaders


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
        try:
            if UserJejakTransaction is not None and get_charge_credits_objs is not None:
                if data.get("data") and data["data"].get("locationsCount"):
                    objs, modifier = await get_charge_credits_objs(
                        user=self.user,
                        category=UserJejakTransactionCategory.COUNT_ROWS,
                        amount=-1 * settings.COUNT_ROWS_MULTIPLIER,
                        details=request.body.decode("utf-8"),
                        free_credit_balance_modifier=free_credit_balance_modifier,
                    )

                    to_create_list += objs
                    free_credit_balance_modifier += modifier

                if data.get("data") and data["data"].get("locations"):
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
                            len(json.dumps(data["data"]))
                            / 1000
                            * settings.BANDWIDTH_MULTIPLIER
                        ),
                        details=request.body.decode("utf-8"),
                        free_credit_balance_modifier=free_credit_balance_modifier,
                    )

                    to_create_list += objs
                    free_credit_balance_modifier += modifier

                if to_create_list:
                    await UserJejakTransaction.objects.abulk_create(to_create_list)
        except (OperationalError, DatabaseError, ImportError, Exception):
            pass

        return data

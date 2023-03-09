import dataclasses
from datetime import date, timedelta
from typing import List, Tuple

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from firebase_admin import auth

from common.enums import CreditType, UserJejakTransactionCategory
from common.models import User, UserJejakTransaction
from generic.schema.enums import DateGroupings


@dataclasses.dataclass
class FirebaseUser:
    def __init__(self, request: HttpRequest):
        self.request = request

    @sync_to_async
    def get_current_user(self):
        auth_key: str = self.request.headers.get("Firebase-Auth-Key", None)

        if auth_key is None:
            return None

        key_contents = auth.verify_id_token(auth_key)
        user = User.objects.get_or_create(
            firebase_id=key_contents["uid"],
            defaults={"firebase_id": key_contents["uid"]},
        )[0]

        return user


def get_date_key(year: int, month: int = None, day: int = None):
    return_str = f"{year:04}"

    if month is not None:
        return_str += f"-{month:02}"

    if day is not None:
        return_str += f"-{day:02}"

    return return_str


def get_default_start_time(type: DateGroupings) -> date:
    """
    This function returns a default start time for gql.UNSET passings.
    Reason for this function is that we want a centralized placed to process such timings.
    """
    today = date.today()
    if type == DateGroupings.YEAR:
        today.month = 1
        today.day = 1
        return today - timedelta(days=18263)

    elif type == DateGroupings.MONTH:
        today.day = 1
        return today - timedelta(days=1500)  # 50 months

    elif type == DateGroupings.DAY:
        return today - timedelta(days=365)

    else:
        raise RuntimeError(f"Unknown date groupings type: {type}")


def get_group_strs(grouping: DateGroupings, prefix: str = "") -> Tuple[List[str], str]:
    if grouping == DateGroupings.YEAR:
        return ([f"{prefix}year"], "years")
    elif grouping == DateGroupings.MONTH:
        return ([f"{prefix}year", f"{prefix}month"], "months")
    elif grouping == DateGroupings.DAY:
        return (
            [
                f"{prefix}year",
                f"{prefix}month",
                f"{prefix}day",
            ],
            "days",
        )

    else:
        raise RuntimeError(f"Unknown date groupings type: {grouping}")


def get_result_comparison_tuple(
    results: List[dict], additional_params: List[str] = [], prefix: str = ""
):
    return_results = []

    for result in results:
        to_append = (
            result.get(f"{prefix}year", None),
            result.get(f"{prefix}month", None),
            result.get(f"{prefix}day", None),
        )
        for param in additional_params:
            to_append = to_append + (result.get(param, None),)

        return_results.append(to_append)

    return return_results


async def get_charge_credits_objs(
    user: User,
    category: UserJejakTransactionCategory,
    amount: int,
    details: str | None = None,
    free_credit_balance_modifier: int = 0,
) -> Tuple[List[UserJejakTransaction], int]:
    free_credit_balance = free_credit_balance_modifier + (
        await user.afree_credit_balance
    )

    if free_credit_balance <= 0:
        return (
            [
                UserJejakTransaction(
                    user_id=user.id,
                    category=category,
                    credit_type=CreditType.PAID,
                    credit_change=amount,
                    details=details,
                )
            ],
            0,
        )

    elif abs(amount) < free_credit_balance:
        return (
            [
                UserJejakTransaction(
                    user_id=user.id,
                    category=category,
                    credit_type=CreditType.FREE,
                    credit_change=amount,
                    details=details,
                )
            ],
            amount,
        )

    else:
        return (
            [
                UserJejakTransaction(
                    user_id=user.id,
                    category=category,
                    credit_type=CreditType.FREE,
                    credit_change=-1 * free_credit_balance,
                    details=details,
                ),
                UserJejakTransaction(
                    user_id=user.id,
                    category=category,
                    credit_type=CreditType.PAID,
                    credit_change=-1 * (abs(amount) - free_credit_balance),
                    details=details,
                ),
            ],
            -1 * free_credit_balance,
        )

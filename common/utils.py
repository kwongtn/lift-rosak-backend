import dataclasses
from datetime import date, timedelta
from typing import TYPE_CHECKING, List, Literal, Tuple

import pendulum
from asgiref.sync import sync_to_async
from django.db.models import Count, Min, Q
from django.http import HttpRequest
from firebase_admin import auth

from common.enums import CreditType, FeatureFlagType, UserJejakTransactionCategory
from common.models import FeatureFlag, User, UserJejakTransaction
from generic.schema.enums import DateGroupings

if TYPE_CHECKING:
    from django.db.models import Model

pendulum.week_starts_at(pendulum.SUNDAY)
pendulum.week_ends_at(pendulum.SATURDAY)


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


def get_date_key(year: int, month: int = None, week: int = None, day: int = None):
    return_str = f"{year:04}"

    if week:
        return f"{return_str}-W{week:02}"

    if month is not None:
        return_str += f"-{month:02}"

    if day is not None:
        return_str += f"-{day:02}"

    return return_str


def get_default_start_time(type: DateGroupings) -> date:
    """
    This function returns a default start time for strawberry.UNSET passings.
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

    elif type == DateGroupings.WEEK:
        today.day = today.day - today.weekday()
        return today - timedelta(days=56)  # 8 weeks

    elif type == DateGroupings.DAY:
        return today - timedelta(days=365)

    else:
        raise RuntimeError(f"Unknown date groupings type: {type}")


def get_group_strs(
    grouping: DateGroupings,
    prefix: str = "",
) -> Tuple[List[str], str]:
    if grouping == DateGroupings.YEAR:
        return ([f"{prefix}__year"], "years")
    elif grouping == DateGroupings.MONTH:
        return ([f"{prefix}__year", f"{prefix}__month"], "months")
    elif grouping == DateGroupings.WEEK:
        return ([f"{prefix}__iso_year", f"{prefix}__week"], "weeks")
    elif grouping == DateGroupings.DAY:
        return (
            [
                f"{prefix}__year",
                f"{prefix}__month",
                f"{prefix}__day",
            ],
            "days",
        )

    else:
        raise RuntimeError(f"Unknown date groupings type: {grouping}")


def get_result_comparison_tuple(
    results: List[dict],
    additional_params: List[str] = [],
    prefix: str = "",
    year_type: Literal["year", "iso_year"] = "year",
):
    return_results = []

    for result in results:
        to_append = (
            result.get(f"{prefix}__{year_type}", None),
            result.get(f"{prefix}__month", None),
            result.get(f"{prefix}__week", None),
            result.get(f"{prefix}__day", None),
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


def get_combinations(groupbys):
    buffer = []
    for k, arr in groupbys.items():
        temp_buffer = []
        for v in arr:
            if buffer:
                for b in buffer:
                    temp_buffer.append({**b, k: v})
            else:
                temp_buffer.append({k: v})

        buffer = temp_buffer

    return buffer


def get_trends(
    groupby_field: str,
    count_model: "Model",
    #
    filters: Q = Q(),
    additional_groupby={},
    start: date = None,
    end: date = date.today(),
    date_group: DateGroupings = DateGroupings.DAY,
    free_range: bool = False,
    add_zero: bool = False,
):
    if start is None:
        start = get_default_start_time(type=date_group)

    display_year = date_group in [
        DateGroupings.DAY,
        DateGroupings.MONTH,
        DateGroupings.WEEK,
        DateGroupings.YEAR,
    ]
    display_month = date_group in [DateGroupings.DAY, DateGroupings.MONTH]
    display_week = date_group in [DateGroupings.WEEK]
    display_day = date_group in [DateGroupings.DAY]

    year_type = "year"
    use_iso_year = False
    if display_week:
        year_type = "iso_year"
        use_iso_year = True

        # Adjust start to Monday of the week
        if start.weekday() != 0:
            start -= timedelta(days=start.weekday())

        # Adjust end to Sunday of the week
        if end.weekday() != 6:
            end += timedelta(days=(6 - end.weekday()))

    (group_strs, range_type) = get_group_strs(
        grouping=date_group,
        prefix=groupby_field,
    )

    for k in additional_groupby.keys():
        group_strs.append(k)

    filter_params = {
        f"{groupby_field}__lte": end,
        f"{groupby_field}__gte": start,
    }

    if free_range:
        filter_params.pop(f"{groupby_field}__lte", None)
        filter_params.pop(f"{groupby_field}__gte", None)

    qs = count_model.objects.filter(filters).filter(**filter_params)

    results = list(
        qs.values(*group_strs)
        .annotate(count=Count("id"))
        .values(*group_strs, "count")
        .order_by(*[f"-{group_str}" for group_str in group_strs])
    )

    interval = pendulum.interval(
        qs.aggregate(min=Min(groupby_field))["min"] if free_range else start,
        date.today() if free_range else end,
    )
    range = interval.range(range_type)

    if add_zero:
        result_types = get_result_comparison_tuple(
            results=results,
            additional_params=[k for k in additional_groupby.keys()],
            prefix=groupby_field,
            year_type=year_type,
        )

        combinations = get_combinations(additional_groupby)
        for elem in range:
            year_val = (
                (elem.isocalendar().year if use_iso_year else elem.year)
                if display_year
                else None
            )
            month_val = elem.month if display_month else None
            week_of_year_val = elem.week_of_year if display_week else None
            day_val = elem.day if display_day else None

            if not combinations:
                to_append = {
                    f"{groupby_field}__{year_type}": year_val,
                    "count": 0,
                }
                if (
                    year_val,
                    month_val,
                    week_of_year_val,
                    day_val,
                ) not in result_types:
                    results.append(
                        {
                            **to_append,
                            f"{groupby_field}__month": month_val,
                            f"{groupby_field}__week": week_of_year_val,
                            f"{groupby_field}__day": day_val,
                        }
                    )

            # Else
            for val in combinations:
                to_append = {
                    **val,
                    f"{groupby_field}__{year_type}": year_val,
                    "count": 0,
                }
                if (
                    year_val,
                    month_val,
                    week_of_year_val,
                    day_val,
                    *val.values(),
                ) not in result_types:
                    results.append(
                        {
                            **to_append,
                            f"{groupby_field}__month": month_val,
                            f"{groupby_field}__week": week_of_year_val,
                            f"{groupby_field}__day": day_val,
                        }
                    )

    for result in results:
        result["date_key"] = get_date_key(
            year=result[f"{groupby_field}__{year_type}"],
            month=result.get(f"{groupby_field}__month", None),
            day=result.get(f"{groupby_field}__day", None),
            week=result[f"{groupby_field}__week"]
            if date_group == DateGroupings.WEEK
            else None,
        )

        if result.get(f"{groupby_field}__day", None):
            result_date = pendulum.date(
                year=result[f"{groupby_field}__{year_type}"],
                month=result[f"{groupby_field}__month"],
                day=result[f"{groupby_field}__day"],
            )
            result["day_of_week"] = result_date.day_of_week

            if result_date.day_of_week == pendulum.SUNDAY:
                new_date = result_date + timedelta(days=6)
            else:
                new_date = result_date
            result["week_of_month"] = new_date.week_of_month

            result["year_week"] = (
                f"{result_date.isocalendar().year}W{result_date.isocalendar().week}"
            )

            new_date = result_date + timedelta(days=1)
            result["is_last_day_of_month"] = new_date.month != result_date.month

            new_date = result_date + timedelta(days=7)
            result["is_last_week_of_month"] = new_date.month != result_date.month

    return sorted(results, key=lambda d: f"{d['date_key']}")


def should_upload_media():
    feat_flag = FeatureFlag.objects.filter(name=FeatureFlagType.IMAGE_UPLOAD).first()
    return feat_flag is not None and feat_flag.enabled

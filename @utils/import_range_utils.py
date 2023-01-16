from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

import numpy as np
from pandas import DataFrame
from psycopg2.extras import DateTimeTZRange

from jejak.models import IdentifierDetailAbstractModel, RangeAbstractModel


# If this end_dt and next start_dt is less than minutes,
# group them together and return
def group_is_close_dt(range_group, minutes=5):
    for index in range(0, len(range_group) - 1):
        if datetime.fromisoformat(
            range_group[index + 1]["start_dt"]
        ) - datetime.fromisoformat(range_group[index]["end_dt"]) < timedelta(
            minutes=minutes
        ):
            range_group[index]["end_dt"] = range_group[index + 1]["end_dt"]
            del range_group[index + 1]
            return True

    return False


def aggregate_start_end_dt(
    dfs: List[DataFrame],
    grouping_keys: List[str],
    dt_target: str = "dt_received",
):
    ranges = defaultdict(list)
    for df in dfs:
        operation_dict = {key: df.loc[:, key].iloc[0] for key in grouping_keys}

        if None not in operation_dict.values():
            ranges[
                tuple([operation_dict[key] for key in operation_dict.keys()])
            ].append(
                {
                    "start_dt": df.aggregate(np.min)[dt_target],
                    "end_dt": df.aggregate(np.max)[dt_target],
                }
            )

    return ranges


def sort_split_dataframes(
    df: DataFrame,
    sort_on: List[str],
    split_on: List[str],
):
    grouped = df.sort_values(sort_on)

    df_groupings = grouped[split_on[0]].astype(str)
    for i in range(1, len(split_on)):
        df_groupings = grouped[split_on[i]].astype(str) + df_groupings

    grouped["group"] = df_groupings.ne(df_groupings.shift()).cumsum()

    return [data for name, data in grouped.groupby("group")]


def get_field_name(df_col_name: str) -> str:
    name_dict = {
        "triprev": "trip_rev",
        "busstop": "bus_stop",
        "enginestatus": "engine_status",
    }
    return name_dict.get(df_col_name, df_col_name)


# As a best practice, left should be the model that has more values
# We assume that all values have been created
def single_fk_range_import(
    df: DataFrame,
    range_model: RangeAbstractModel,
    left_model: IdentifierDetailAbstractModel,
    right_model: IdentifierDetailAbstractModel,
    dt_target: str = "dt_received",
):
    left_key = left_model.__name__.lower()
    right_key = right_model.__name__.lower()

    # Sort then assign groupings based on change of value
    print(f"⏩ [{left_key}, {right_key}] Sorting & splitting data into dataframes...")
    ranges = aggregate_start_end_dt(
        dfs=sort_split_dataframes(
            df=df,
            sort_on=[left_key, dt_target],
            split_on=[left_key, right_key],
        ),
        grouping_keys=[left_key, right_key],
    )

    print(f"⏩ [{left_key}, {right_key}] Regrouping values...")
    for key in ranges:
        if len(ranges[key]) > 1:
            while group_is_close_dt(ranges[key]):
                pass

    left_obj_dict: dict = left_model.objects.filter(
        identifier__in=df[left_key].dropna().unique()
    ).in_bulk(field_name="identifier")

    right_obj_dict: dict = right_model.objects.filter(
        identifier__in=df[right_key].dropna().unique()
    ).in_bulk(field_name="identifier")

    print(f"⏩ [{left_key}, {right_key}] Inserting ranges...")
    to_create = []
    for (key, range_item) in ranges.items():
        if "<NA>" in [str(i) for i in key]:
            continue

        key_data = {
            get_field_name(left_key) + "_id": left_obj_dict[str(key[0])].id,
            get_field_name(right_key) + "_id": right_obj_dict[str(key[1])].id,
        }

        for elem in range_item:
            to_create.append(
                range_model(
                    **key_data,
                    dt_range=DateTimeTZRange(
                        lower=elem["start_dt"],
                        upper=elem["end_dt"],
                        bounds="[]",
                    ),
                )
            )

    return_val = range_model.objects.bulk_create(to_create, ignore_conflicts=True)
    print(f"⏩ [{left_key}, {right_key}] Done.")

    return return_val


# We assume that objects that require other objects to be created
# first are already created
def multi_fk_row_import(
    df: DataFrame,
    groupings: dict,
    target_str: str,
    target_model: IdentifierDetailAbstractModel,
):
    print(f"⏩ [{str(groupings.keys())} -> {target_str}] Aggregrating values...")
    df2 = df[[target_str, *groupings.keys()]].dropna().drop_duplicates()

    print(f"⏩ [{str(groupings.keys())} -> {target_str}] Obtaining existing values...")
    dicts = {
        key: model.objects.filter(
            identifier__in=df2[key].dropna().unique(),
        ).in_bulk(field_name="identifier")
        for (key, model) in groupings.items()
    }

    print(
        f"⏩ [{str(groupings.keys())} -> {target_str}] Iterating & inserting values..."
    )
    to_bulk_create_dict = []
    for index, row in df2.iterrows():
        data_dict = {"identifier": row[target_str]}

        for key in groupings.keys():
            data_dict[key + "_id"] = dicts[key].get(row[key]).id

        to_bulk_create_dict.append(data_dict)

    return target_model.objects.bulk_create(
        [target_model(**elem_dict) for elem_dict in to_bulk_create_dict],
        ignore_conflicts=True,
    )

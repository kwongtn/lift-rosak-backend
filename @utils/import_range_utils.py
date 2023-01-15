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
    target_keys: List[str],
    grouping_keys: List[str],
    dt_target: str = "dt_gps",
):
    ranges = defaultdict(list)
    for elem in dfs:
        operation_dict = {
            key: elem.loc[:, key].iloc[0] for key in [*target_keys, *grouping_keys]
        }

        if None not in [operation_dict[target_key] for target_key in target_keys]:
            ranges[
                tuple([operation_dict[key] for key in operation_dict.keys()])
            ].append(
                {
                    "start_dt": elem.aggregate(np.min)[dt_target],
                    "end_dt": elem.aggregate(np.max)[dt_target],
                }
            )

    return ranges


# As a best practice, left should be the model that has more values
# We assume that all values have been created
def single_fk_range_import(
    df: DataFrame,
    range_model: RangeAbstractModel,
    left_model: IdentifierDetailAbstractModel,
    right_model: IdentifierDetailAbstractModel,
    left_key: str,
    right_key: str,
    dt_target: str = "dt_gps",
):
    # Sort then assign groupings based on change of value
    print(f"⏩ [{left_key}, {right_key}] Sorting values...")
    grouped = df.sort_values([left_key, dt_target]).dropna(subset=[left_key, right_key])

    df_groupings = grouped[left_key].astype(str) + grouped[right_key].astype(str)
    grouped["group"] = df_groupings.ne(df_groupings.shift()).cumsum()

    print(f"⏩ [{left_key}, {right_key}] Splitting data into dataframes...")
    dfs = [data for name, data in grouped.groupby("group")]

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        target_keys=[left_key],
        grouping_keys=[right_key],
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
    for key in ranges:
        for elem in ranges[key]:
            to_create.append(
                range_model(
                    **{
                        left_key + "_id": left_obj_dict[str(key[0])].id,
                        right_key + "_id": right_obj_dict[str(key[1])].id,
                    },
                    dt_range=DateTimeTZRange(
                        lower=elem["start_dt"],
                        upper=elem["end_dt"],
                        bounds="[]",
                    ),
                )
            )

    range_model.objects.bulk_create(to_create, ignore_conflicts=True)
    print(f"⏩ [{left_key}, {right_key}] Done.")


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

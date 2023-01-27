from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
from django.db.models import Model, Q
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
            start_dt = np.min(df[dt_target])
            end_dt = np.max(df[dt_target])

            # print(dt_target, start_dt, end_dt)
            ranges[tuple(operation_dict.values())].append(
                {
                    "start_dt": start_dt,
                    "end_dt": end_dt,
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
    dfs = sort_split_dataframes(
        df=df,
        sort_on=[left_key, dt_target],
        split_on=[left_key, right_key],
    )

    print(
        f"⏩ [{left_key}, {right_key}] {len(dfs)} dataframes created, aggregrating values..."
    )

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=[left_key, right_key],
    )

    print(f"⏩ [{left_key}, {right_key}] Grouping close values...")
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
    groupings: Dict[str, Model],
    target_str: str,
    target_model: IdentifierDetailAbstractModel,
):
    target_str = target_model.__name__.lower()

    debug_prefix = f"[{str(groupings.keys())} -> {target_str}]"

    print(f"⏩ {debug_prefix} Aggregrating values...")
    df2 = df[[target_str, *groupings.keys()]].dropna().drop_duplicates()

    print(f"⏩ {debug_prefix} Obtaining existing values...")
    dicts = {
        key: model.objects.filter(
            identifier__in=df2[key].dropna().unique(),
        ).in_bulk(field_name="identifier")
        for (key, model) in groupings.items()
    }

    print(f"⏩ {debug_prefix} Iterating & inserting values...")
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


async def single_side_multi_fk_range_import(
    df: DataFrame,
    range_model: RangeAbstractModel,
    groupings: Dict[str, Model],
    side_model: Model,
    dt_target: str = "dt_received",
):
    side_model_key = side_model.__name__.lower()
    debug_prefix = f"[{str(groupings.keys())} -> {side_model_key}]"

    # Aggregate data based on dt grouping
    print(f"⏩ {debug_prefix} Sorting & aggregrating values...")
    dfs = sort_split_dataframes(
        df=df,
        sort_on=[*groupings.keys(), dt_target],
        split_on=[*groupings.keys(), side_model_key],
    )

    print(f"⏩ {debug_prefix} {len(dfs)} dataframes created, aggregrating values...")

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=[side_model_key, *groupings.keys()],
    )

    print(f"⏩ {debug_prefix} Grouping close values...")
    for key in ranges:
        if len(ranges[key]) > 1:
            while group_is_close_dt(ranges[key]):
                pass

    dicts = {
        key: model.objects.filter(
            identifier__in=df[key].dropna().unique(),
        ).in_bulk(field_name="identifier")
        for (key, model) in groupings.items()
    }

    print(f"⏩ {debug_prefix} Generating query...")
    criteria = Q()
    for key in set(ranges.keys()):
        # First key is always identifier
        query_dict = {"identifier": key[0]}

        counter = 1
        for group in groupings.keys():
            query_dict[group + "_id"] = dicts[group][key[counter]].id
            counter += 1

        criteria |= Q(**query_dict)

    # Assert criteria is not empty, else it will select everything
    assert len(criteria) > 0

    print(f"⏩ {debug_prefix} Requesting from db...")
    instances = side_model.objects.filter(criteria).select_related(*groupings.keys())

    print(f"⏩ {debug_prefix} Generating dict over {len(instances)} values...")
    instances_dict = {}
    for instance in instances:
        # if counter % 100 == 0:
        print(".", end="")

        instances_dict[
            tuple(
                [
                    instance.identifier,
                    *[
                        getattr(instance, fk_key).identifier
                        for fk_key in groupings.keys()
                    ],
                ]
            )
        ] = instance.id

    print("⏩ Inserting values...")
    to_create = []
    for key in ranges:
        for elem in ranges[key]:
            to_create.append(
                range_model(
                    dt_range=DateTimeTZRange(
                        lower=elem["start_dt"],
                        upper=elem["end_dt"],
                        bounds="[]",
                    ),
                    **{side_model_key + "_id": instances_dict[key]},
                )
            )

    range_model.objects.bulk_create(to_create, ignore_conflicts=True)


def multi_fk_range_import(
    df: DataFrame,
    range_model: RangeAbstractModel,
    left_model: Model,
    right_model: Model,
    left_groupings: List[Model],
    right_groupings: List[Model],
    dt_target: str = "dt_received",
):
    left_groupings_keys = [model.__name__.lower() for model in left_groupings]
    right_groupings_keys = [model.__name__.lower() for model in right_groupings]
    grouping_keys_set = set([*left_groupings_keys, *right_groupings_keys])

    left_model_key = left_model.__name__.lower()
    right_model_key = right_model.__name__.lower()

    debug_prefix = (
        f"[{''.join(left_groupings_keys)} -> {''.join(right_groupings_keys)}]"
    )

    # Aggregate data based on dt grouping
    print(f"⏩ {debug_prefix} Sorting & aggregrating values...")
    dfs = sort_split_dataframes(
        df=df,
        sort_on=[*grouping_keys_set, left_model_key, dt_target],
        split_on=[*grouping_keys_set, left_model_key, right_model_key],
    )

    print(f"⏩ {debug_prefix} {len(dfs)} dataframes created, aggregrating values...")

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=[left_model_key, right_model_key, *grouping_keys_set],
    )

    print(f"⏩ {debug_prefix} Grouping close values...")
    for key in ranges:
        if len(ranges[key]) > 1:
            while group_is_close_dt(ranges[key]):
                pass

    dicts = {
        model.__name__.lower(): model.objects.filter(
            identifier__in=df[model.__name__.lower()].dropna().unique(),
        ).in_bulk(field_name="identifier")
        for model in set([*left_groupings, *right_groupings])
    }

    print(f"⏩ {debug_prefix} Generating & requesting comparison dict...")

    def get_criteria(start_num: int, grouping_keys: List[str]):
        criteria = Q()
        for key in ranges.keys():
            # First key is always identifier
            query_dict = {"identifier": key[start_num]}

            counter = start_num + 1
            for group in grouping_keys:
                query_dict[group + "_id"] = dicts[group][key[counter]].id
                counter += 1

            criteria |= Q(**query_dict)

        return criteria

    left_criteria = get_criteria(0, left_groupings_keys)
    right_criteria = get_criteria(1 + len(left_groupings), right_groupings_keys)

    # Assert criteria is not empty, else it will select everything
    assert len(left_criteria) > 0
    assert len(right_criteria) > 0

    left_instances = left_model.objects.filter(left_criteria).select_related(
        *left_groupings_keys
    )
    right_instances = right_model.objects.filter(right_criteria).select_related(
        *right_groupings_keys
    )

    def get_instances_dict(instances, groupings_keys):
        instances_dict = {}
        for instance in instances:
            instances_dict[
                tuple(
                    [
                        instance.identifier,
                        *[
                            getattr(instance, grouping_key).identifier
                            for grouping_key in groupings_keys
                        ],
                    ]
                )
            ] = instance

        return instances_dict

    print(f"⏩ {debug_prefix} Requesting left instances...")
    left_instances_dict = get_instances_dict(
        instances=left_instances,
        groupings_keys=left_groupings_keys,
    )
    print(f"⏩ {debug_prefix} Requesting right instances...")
    right_instances_dict = get_instances_dict(
        instances=right_instances,
        groupings_keys=right_groupings_keys,
    )

    print("⏩ Inserting values...")
    to_create = []
    for key in ranges:
        for elem in ranges[key]:
            to_create.append(
                range_model(
                    dt_range=DateTimeTZRange(
                        lower=elem["start_dt"],
                        upper=elem["end_dt"],
                        bounds="[]",
                    ),
                    **{
                        left_model_key
                        + "_id": left_instances_dict[
                            key[0 : 1 + len(left_groupings_keys)]
                        ].id,
                        right_model_key
                        + "_id": right_instances_dict[
                            key[
                                1
                                + len(left_groupings_keys) : 1
                                + len(left_groupings_keys)
                                + 1
                                + len(right_groupings_keys)
                            ]
                        ].id,
                    },
                )
            )

    range_model.objects.bulk_create(to_create, ignore_conflicts=True)

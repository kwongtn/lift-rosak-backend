import argparse
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List

import polars as pl
from django.db.models import Model, Q
from polars import DataFrame, LazyFrame
from psycopg2.extras import DateTimeTZRange

from jejak.models import IdentifierDetailAbstractModel, RangeAbstractModel
from utils.constants import DT_TARGET, GROUP_THRESHOLDS
from utils.db import wrap_errors

argParser = argparse.ArgumentParser()
argParser.add_argument("-f", "--file", help="Input filename.")
args = argParser.parse_args()
INPUT_FILENAME: str = args.file
FILENAME = INPUT_FILENAME.split("/")[-1]

sleep_time = 5
chunk_size = int(1e4)


# If this end_dt and next start_dt is less than minutes,
# group them together and return
def group_is_close_dt(range_group, model_str: str):
    for index in range(0, len(range_group) - 1):
        threshold = GROUP_THRESHOLDS[model_str]

        if (
            range_group[index + 1]["start_dt"] - range_group[index]["end_dt"]
            < threshold
        ):
            range_group[index]["end_dt"] = max(
                range_group[index]["end_dt"], range_group[index + 1]["end_dt"]
            )
            del range_group[index + 1]
            return True

    return False


def aggregate_start_end_dt(
    dfs: List[DataFrame],
    grouping_keys: List[str],
    dt_target: str = DT_TARGET,
):
    ranges = defaultdict(list)
    for df in dfs:
        operation_dict = {key: df.select(key)[0].item() for key in grouping_keys}

        if None not in operation_dict.values():
            start_dt = datetime.fromisoformat(df.select(pl.min(dt_target)).item())
            end_dt = datetime.fromisoformat(df.select(pl.max(dt_target)).item())

            # print(dt_target, start_dt, end_dt)
            ranges[tuple(operation_dict.values())].append(
                {
                    "start_dt": min(start_dt, end_dt),
                    "end_dt": max(start_dt, end_dt),
                }
            )

    return ranges


def sort_split_dataframes(
    df: LazyFrame,
    sort_on: List[str],
    split_on: List[str],
) -> List[DataFrame]:
    computed = pl.concat_str(split_on).fill_null("")

    grouped = (
        df.select(pl.col(set([*sort_on, *split_on])))
        .sort(*sort_on)
        .select(
            pl.all(),
            # Invert cause cumsum adds all True, and that each True means change in data
            is_same=~computed.eq(computed.shift()).fill_null(False),
        )
        .select(
            pl.exclude("is_same"),
            group=pl.cum_sum("is_same"),
        )
    )

    return [data for name, data in grouped.collect().group_by(["group"])]


def get_field_name(df_col_name: str) -> str:
    name_dict = {
        "triprev": "trip_rev",
        "busstop": "bus_stop",
        "enginestatus": "engine_status",
    }
    return name_dict.get(df_col_name, df_col_name)


def get_criteria(
    grouping_keys: List[str],
    ranges: defaultdict[Any, list],
    dicts: dict,
    start_num: int = 0,
):
    criteria = Q()
    for key in ranges.keys():
        # First key is always identifier
        query_dict = {"identifier": key[start_num]}

        counter = start_num + 1
        for group in grouping_keys:
            query_dict[group + "_id"] = dicts[group][key[counter]].id
            counter += 1

        criteria |= Q(**query_dict)

    # Assert criteria is not empty, else it will select everything
    assert len(criteria) > 0

    return criteria


def instance_mapping_fn(
    criteria, groupings, side_model: Model, debug_prefix="", progress_suffix=""
):
    instances_dict = {}

    instances = side_model.objects.filter(criteria).select_related(*groupings.keys())

    print(f"{FILENAME} ⏩ {debug_prefix} Generating dict... {progress_suffix}")
    for instance in instances:
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

    return instances_dict


# As a best practice, left should be the model that has more values
# We assume that all values have been created
def single_fk_range_import(
    df: LazyFrame,
    range_model: RangeAbstractModel,
    left_model: IdentifierDetailAbstractModel,
    right_model: IdentifierDetailAbstractModel,
    dt_target: str = DT_TARGET,
):
    global sleep_time
    left_key = left_model.__name__.lower()
    right_key = right_model.__name__.lower()

    debug_prefix = f"[{left_key} -> {right_key}]"

    # Sort then assign groupings based on change of value
    print(f"{FILENAME} 🔪 {debug_prefix} Sorting & splitting data into dataframes...")
    dfs = sort_split_dataframes(
        df=df,
        sort_on=[left_key, dt_target],
        split_on=[left_key, right_key],
    )

    print(
        f"{FILENAME} 📦 {debug_prefix} {len(dfs):,} dataframes created, aggregrating values..."
    )

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=[left_key, right_key],
    )

    print(f"{FILENAME} ⏩ {debug_prefix} Grouping close values...")
    for key in ranges:
        if len(ranges[key]) > 1:
            while group_is_close_dt(ranges[key], range_model.__name__):
                pass

    left_obj_dict: dict = {}
    right_obj_dict: dict = {}

    while True:
        try:
            left_obj_dict = left_model.objects.filter(
                identifier__in=df.select(pl.col(left_key))
                .drop_nulls()
                .unique()
                .collect()
                .get_columns()[0]
                .to_list()
            ).in_bulk(field_name="identifier")

            right_obj_dict = right_model.objects.filter(
                identifier__in=df.select(pl.col(right_key))
                .drop_nulls()
                .unique()
                .collect()
                .get_columns()[0]
                .to_list()
            ).in_bulk(field_name="identifier")

        except Exception as e:
            print(e)
            print(f"{FILENAME} ❗ Error, retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
            sleep_time += 5

            continue

        break

    print(f"{FILENAME} ⏩ {debug_prefix} Inserting ranges...")
    to_create = []
    for key, range_item in ranges.items():
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

    wrap_errors(
        fn=range_model.objects.bulk_create,
        debug_prefix=debug_prefix,
        objs=to_create,
        batch_size=2000,
        ignore_conflicts=True,
    )


def replace_identifier_with_id(
    df_collected: DataFrame,
    groupings: dict,
    call_all_from_db=False,
    drop_replaced=False,
) -> DataFrame:
    df = deepcopy(df_collected)

    model: Model
    for model in groupings.values():
        model_name = model.__name__.lower()

        # Probably issue is here, cause we collapse everything to identifier only, without taking into account other values
        providers_dict = (
            model.objects.all()
            if call_all_from_db
            else model.objects.filter(identifier__in=df_collected[model_name].unique())
        ).in_bulk(field_name="identifier")

        df_dict = defaultdict(tuple)
        for elem in providers_dict.values():
            df_dict[f"{model_name}_id"] += (elem.id,)
            df_dict[model_name] += (elem.identifier,)

        fk_df = pl.DataFrame(df_dict)

        # We deal with the collected one cause we don't wanna do duplicate work
        df = df.join(fk_df, on=model_name, how="left")
        if drop_replaced:
            df = df.drop(model_name)

    return df


# We assume that objects that require other objects to be created
# first are already created
def multi_fk_row_import(
    df: LazyFrame,
    groupings: Dict[str, Model],
    target_model: IdentifierDetailAbstractModel,
    call_all_from_db=True,
):
    global sleep_time
    target_str = target_model.__name__.lower()

    debug_prefix = f"[{list(groupings.keys())} -> {target_str}]"

    print(f"{FILENAME} 📦 {debug_prefix} Aggregrating values...")
    df_collected: DataFrame = (
        df.select(target_str, *groupings.keys())
        .unique()
        .drop_nulls()
        .rename({target_str: "identifier"})
        .collect()
    )

    while True:
        try:
            print(f"{FILENAME} ⏩ {debug_prefix} Obtaining existing values...")

            df_collected = replace_identifier_with_id(
                df_collected=df_collected,
                groupings=groupings,
                call_all_from_db=call_all_from_db,
                drop_replaced=True,
            )

        except Exception as e:
            print(e)
            print(f"{FILENAME} ❗ Error, retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
            sleep_time += 5

            continue

        break

    print(df_collected)

    print(
        f"{FILENAME} ⏩ {debug_prefix} Iterating & inserting {len(df_collected)} values..."
    )
    to_bulk_create_dict = [row for row in df_collected.iter_rows(named=True)]

    wrap_errors(
        fn=target_model.objects.bulk_create,
        objs=[target_model(**elem_dict) for elem_dict in to_bulk_create_dict],
        debug_prefix=debug_prefix,
        batch_size=2000,
        ignore_conflicts=True,
    )

    print(f"{FILENAME} ✅ {debug_prefix} Done import.")
    return df_collected


def get_fk_df(df_collected: DataFrame, groupings: Dict[str, Model], model: Model):
    model_name = model.__name__.lower()
    qs = model.objects.filter(identifier__in=df_collected[model_name].unique())

    df_dict = defaultdict(tuple)
    for elem in qs:
        for key in groupings.keys():
            df_dict[f"{key}_id"] += (getattr(elem, f"{key}_id"),)

        df_dict["identifier"] += (elem.identifier,)
        df_dict[f"{model_name}_id"] += (elem.id,)

    return pl.DataFrame(df_dict)


def single_side_multi_fk_range_import(
    df: LazyFrame,
    range_model: RangeAbstractModel,
    groupings: Dict[str, Model],
    side_model: Model,
    dt_target: str = DT_TARGET,
):
    global sleep_time
    side_model_key = side_model.__name__.lower()
    debug_prefix = f"[{list(groupings.keys())} -> {side_model_key}]"

    # Aggregate data based on dt grouping
    print(f"{FILENAME} 📦 {debug_prefix} Sorting & aggregrating values...")

    grouping_key_ids = [f"{key}_id" for key in groupings.keys()]
    to_drop = [side_model_key, *grouping_key_ids]
    df_collected = df.collect()

    side_df = get_fk_df(df_collected, groupings, side_model)

    new_df = (
        replace_identifier_with_id(
            df_collected=df_collected,
            groupings=groupings,
            call_all_from_db=True,
        ).join(
            side_df.rename({"identifier": side_model_key}),
            on=to_drop,
            how="left",
        )
        # .sort([*grouping_key_ids, dt_target])
    )

    dfs = sort_split_dataframes(
        df=new_df.lazy(),
        sort_on=[grouping_key_ids[0], dt_target],
        split_on=[*grouping_key_ids, f"{side_model_key}_id"],
    )

    print(
        f"{FILENAME} ⏩ {debug_prefix} {len(dfs):,} dataframes created, aggregrating values..."
    )

    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=[
            # *grouping_key_ids,
            f"{side_model_key}_id",
        ],
    )

    print(f"{FILENAME} ⏩ {debug_prefix} Grouping close values...")
    for key in ranges:
        if len(ranges[key]) > 1:
            while group_is_close_dt(ranges[key], range_model.__name__):
                pass

    ranges_size = len(ranges)
    progress_size = 0
    while ranges:
        chunk = defaultdict(list)
        if chunk_size > len(ranges.keys()):
            chunk = ranges
            ranges = defaultdict(list)

        else:
            for key in list(ranges.keys())[:chunk_size]:
                chunk[key] = ranges[key]
                ranges.pop(key)

        progress_size += len(chunk)

        progress_suffix = f"[{progress_size:,}/{ranges_size:,}]"

        print(f"{FILENAME} ⏩ {debug_prefix} Inserting values... {progress_suffix}")
        to_create = []
        for key, elems in chunk.items():
            for elem in elems:
                # print(elem)
                to_create.append(
                    range_model(
                        dt_range=DateTimeTZRange(
                            lower=elem["start_dt"],
                            upper=elem["end_dt"],
                            bounds="[]",
                        ),
                        **{side_model_key + "_id": key[0]},
                    )
                )

        wrap_errors(
            fn=range_model.objects.bulk_create,
            objs=to_create,
            batch_size=2000,
            ignore_conflicts=True,
            debug_prefix=debug_prefix,
        )

        print(f"{FILENAME} ✅ {debug_prefix} Done. {progress_suffix}")


def multi_fk_range_import(
    df: LazyFrame,
    range_model: RangeAbstractModel,
    left_model: Model,
    right_model: Model,
    left_groupings: List[Model],
    right_groupings: List[Model],
    dt_target: str = DT_TARGET,
):
    global sleep_time
    left_groupings: Dict[str, Model] = {
        model.__name__.lower(): model for model in left_groupings
    }
    right_groupings: Dict[str, Model] = {
        model.__name__.lower(): model for model in right_groupings
    }

    left_groupings_keys = left_groupings.keys()
    right_groupings_keys = right_groupings.keys()

    left_model_key = left_model.__name__.lower()
    right_model_key = right_model.__name__.lower()

    debug_prefix = f"[{str(left_groupings_keys)} -> {str(right_groupings_keys)}]"
    df_collected = df.collect().drop(
        "latitude", "longitude", "dt_gps", "dir", "speed", "angle", "accessibility"
    )

    for groupings, model in [
        (left_groupings, left_model),
        (right_groupings, right_model),
    ]:
        print(f"{FILENAME} ⏩ {debug_prefix} Requesting {model.__name__} instances... ")

        fk_df = get_fk_df(df_collected, groupings, model)
        print("fk_df")
        print(fk_df)
        model_key = model.__name__.lower()

        df_collected = (
            replace_identifier_with_id(
                df_collected=df_collected,
                groupings=groupings,
                call_all_from_db=True,
            ).join(
                fk_df.rename({"identifier": model_key}),
                on=[model_key, *[f"{key}_id" for key in groupings.keys()]],
                how="left",
            )
            # .sort([*grouping_key_ids, dt_target])
        )
        print(df_collected)

    grouping_ids = [
        f"{k}_id"
        for k in [
            left_model_key,
            *left_groupings_keys,
            right_model_key,
            *right_groupings_keys,
        ]
    ]

    # Aggregate data based on dt grouping
    print(f"{FILENAME} 📦 {debug_prefix} Sorting & aggregrating values...")
    dfs = sort_split_dataframes(
        df=df_collected.lazy(),
        sort_on=[left_model_key, dt_target],
        split_on=grouping_ids,
    )

    print(
        f"{FILENAME} ⏩ {debug_prefix} {len(dfs):,} dataframes created, aggregrating values..."
    )
    ranges = aggregate_start_end_dt(
        dfs=dfs,
        grouping_keys=grouping_ids,
    )

    # print(f"{FILENAME} ⏩ {debug_prefix} Grouping close values...")
    # for key in ranges:
    #     if len(ranges[key]) > 1:
    #         while group_is_close_dt(ranges[key], range_model.__name__):
    #             pass

    ranges_size = len(ranges)
    progress_size = 0
    while ranges:
        chunk = defaultdict(list)
        if chunk_size > len(ranges.keys()):
            chunk = ranges
            ranges = defaultdict(list)

        else:
            for key in list(ranges.keys())[:chunk_size]:
                chunk[key] = ranges[key]
                ranges.pop(key)

        progress_size += len(chunk)

        progress_suffix = f"[{progress_size:,}/{ranges_size:,}]"

        print(f"{FILENAME} ⏩ Inserting values... {progress_suffix}")
        to_create = []
        for key, elems in chunk.items():
            for elem in elems:
                # print(key, elem)
                range_obj = range_model(
                    dt_range=DateTimeTZRange(
                        lower=elem["start_dt"],
                        upper=elem["end_dt"],
                        bounds="[]",
                    ),
                    **{left_model_key + "_id": key[0]},
                )

                for i in range(len(grouping_ids)):
                    setattr(range_obj, grouping_ids[i], key[i])

                to_create.append(range_obj)

        wrap_errors(
            fn=range_model.objects.bulk_create,
            debug_prefix=debug_prefix,
            objs=to_create,
            batch_size=1000,
            ignore_conflicts=True,
        )

        print(f"{FILENAME} ✅ {debug_prefix} Done. {progress_suffix}")

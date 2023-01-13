from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

import numpy as np
from pandas import DataFrame

from jejak.models import IdentifierDetailAbstractModel


def identifier_detail_abstract_model_input(
    model: IdentifierDetailAbstractModel, identifiers: List[str]
):
    return model.objects.bulk_create(
        [model(identifier=identifier) for identifier in identifiers],
        ignore_conflicts=True,
    )


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
    target_key: str,
    grouping_keys: List[str],
    dt_target: str = "dt_gps",
):
    ranges = defaultdict(list)
    for elem in dfs:
        operation_dict = {
            key: elem.loc[:, key].iloc[0] for key in [target_key, *grouping_keys]
        }

        if operation_dict[target_key] is not None:
            ranges[
                tuple([operation_dict[key] for key in operation_dict.keys()])
            ].append(
                {
                    "start_dt": elem.aggregate(np.min)[dt_target],
                    "end_dt": elem.aggregate(np.max)[dt_target],
                }
            )

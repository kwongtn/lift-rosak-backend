from datetime import datetime, timedelta
from typing import List

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

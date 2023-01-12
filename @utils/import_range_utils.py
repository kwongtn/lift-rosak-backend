from typing import List

from jejak.models import IdentifierDetailAbstractModel


def identifier_detail_abstract_model_input(
    model: IdentifierDetailAbstractModel, identifiers: List[str]
):
    return model.objects.bulk_create(
        [model(identifier=identifier) for identifier in identifiers],
        ignore_conflicts=True,
    )

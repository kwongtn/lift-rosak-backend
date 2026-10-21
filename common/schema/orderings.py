import strawberry
import strawberry_django
from django.db.models import QuerySet
from strawberry.types import Info
from strawberry_django.ordering import OrderSequence, process_order

from common.models import Media


@strawberry_django.ordering.order(Media)
class MediaOrder:
    # No `uploader`: sorting by it would group a hidden-uploader photo (anonymous
    # spotting) between the visible photos of the same user.
    created: strawberry.auto
    modified: strawberry.auto

    @strawberry_django.order_field
    def order(
        self,
        info: Info,
        queryset: QuerySet,
        prefix: str,
        sequence: dict[str, OrderSequence] | None,
    ) -> tuple[QuerySet, list]:
        """The requested keys, then the primary key last.

        `created` / `modified` can tie (several photos in one millisecond), and
        offset paging over tied rows skips some and repeats others, so the feed
        needs a unique final key.

        `process_order(..., skip_object_order_method=True)` and `OrderSequence` are
        strawberry-django internals (pinned to 0.82.x in pyproject.toml). An upgrade
        that changes them fails `common.tests.MediasFeedPagingTests`: run it first.
        """
        queryset, args = process_order(
            self,  # type: ignore[arg-type]  # the decorator hides the definition
            info,
            queryset,
            sequence=sequence,
            prefix=prefix,
            skip_object_order_method=True,
        )
        return queryset, [*args, "pk"]

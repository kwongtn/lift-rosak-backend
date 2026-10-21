import strawberry
import strawberry_django

from common.models import Media


@strawberry_django.ordering.order(Media)
class MediaOrder:
    # No `uploader`: sorting by it would group a hidden-uploader photo (anonymous
    # spotting) between the visible photos of the same user.
    created: strawberry.auto
    modified: strawberry.auto

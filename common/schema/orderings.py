import strawberry
import strawberry_django

from common.models import Media


@strawberry_django.ordering.order(Media)
class MediaOrder:
    uploader: strawberry.auto
    created: strawberry.auto
    modified: strawberry.auto

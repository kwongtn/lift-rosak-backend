from typing import Optional

import strawberry
import strawberry_django

from chartography import models


@strawberry_django.type(models.Source)
class Source:
    id: strawberry.ID
    name: str
    description: str
    official_site: Optional[str]
    icon_url: Optional[str]

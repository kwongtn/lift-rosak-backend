from typing import Optional

import strawberry


@strawberry.input
class TriggerInput:
    force: Optional[bool]

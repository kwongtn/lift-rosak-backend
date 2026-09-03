"""Shared keyset-cursor helpers for SocialMediaLink pagination.

Both the root ``publicSocialMediaLinks(incidentId, ...)`` resolver and the nested
``CalendarIncidentScalar.links(first, after)`` field paginate over the same
ordering (``created DESC, id DESC``) and must be able to consume each other's
cursors (the frontend takes a nested page-1 cursor, then requests continuation
pages through the root query — same window, same ordering, same cursor).

Cursor wire format: base64("<created isoformat>|<id>"), decoded to a
(created, id) tuple and applied as the keyset predicate
``created < cursor OR (created = cursor AND id < cursor_id)``.
"""

import base64
from datetime import datetime


def encode_keyset_cursor(created: datetime, link_id: int) -> str:
    return base64.b64encode(f"{created.isoformat()}|{link_id}".encode()).decode()


def decode_keyset_cursor(cursor: str) -> tuple[datetime, int]:
    payload = base64.b64decode(cursor.encode()).decode()
    created_str, link_id_str = payload.split("|", 1)
    return datetime.fromisoformat(created_str), int(link_id_str)

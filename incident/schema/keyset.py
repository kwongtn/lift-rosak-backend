"""Shared keyset-cursor helpers for DESC ``(timestamp, id)`` pagination.

The helpers are deliberately **field-agnostic**: they encode a timestamp and a
row id and know nothing about which column the timestamp came from. What the
caller must supply, and what the caller must keep in agreement with its own
``order_by``, is *which* timestamp.

Cursor wire format: base64("<isoformat>|<id>"), decoded to a ``(ts, id)`` tuple
and applied by the caller as the keyset predicate
``ts < cursor OR (ts = cursor AND id < cursor_id)``. Because the payload is an
opaque ISO datetime, a cursor minted for one column will happily be *accepted*
by a consumer that orders on another — it just resumes at the wrong place. So
the encoding is shareable between surfaces only while they order on the SAME
column, and that is the case for the two ``SocialMediaLink`` surfaces:

* the root ``publicSocialMediaLinks(incidentId, ...)`` resolver and the nested
  ``CalendarIncidentScalar.links(first, after)`` field both order
  ``occurred_at DESC, id DESC`` and must be able to consume each other's cursors
  (the frontend takes a nested page-1 cursor, then requests continuation pages
  through the root query — same window, same ordering, same cursor).

``get_line_status_reports`` also uses these helpers, but on
``LineStatusReport.created`` — that model has no event-time column, and
deliberately so: a status report *is* its creation instant.
"""

import base64
from datetime import datetime


def encode_keyset_cursor(ts: datetime, row_id: int) -> str:
    return base64.b64encode(f"{ts.isoformat()}|{row_id}".encode()).decode()


def decode_keyset_cursor(cursor: str) -> tuple[datetime, int]:
    payload = base64.b64decode(cursor.encode()).decode()
    ts_str, row_id_str = payload.split("|", 1)
    return datetime.fromisoformat(ts_str), int(row_id_str)

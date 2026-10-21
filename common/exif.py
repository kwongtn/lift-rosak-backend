"""Remove the GPS block from a photo's EXIF without re-encoding it.

Phone photos carry the position they were taken at. We keep the capture time and the
camera make and model (moderators read them, and ``CalendarIncidentMedia.timestamp`` is
the EXIF ``DateTime``) and drop only the GPS IFD (tag 0x8825).

The edit is done on the EXIF APP1 segment in place, so the image data, the ICC profile
and every other EXIF tag stay byte-for-byte as they were.
"""

import logging
import struct

logger = logging.getLogger(__name__)

JPEG_MAGIC = b"\xff\xd8\xff"
_EXIF_HEADER = b"Exif\x00\x00"
_APP1 = 0xE1
_GPS_INFO = 0x8825
MAX_GPS_ENTRIES = 4
# TIFF field type -> bytes per value: BYTE, ASCII, SHORT, LONG, RATIONAL, SBYTE,
# UNDEFINED, SSHORT, SLONG, SRATIONAL, FLOAT, DOUBLE.
_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
}


def _zero(tiff: bytearray, start: int, length: int) -> None:
    # A slice assignment past the end would grow the array, so check first.
    if start < 0 or start + length > len(tiff):
        raise ValueError("EXIF offset outside the TIFF block")
    tiff[start : start + length] = bytes(length)


def _zero_ifd(tiff: bytearray, order: str, offset: int) -> None:
    """Wipe the IFD at `offset` and every out-of-line value it points at."""
    (count,) = struct.unpack_from(order + "H", tiff, offset)
    for i in range(count):
        field_type, n_values, value = struct.unpack_from(
            order + "HII", tiff, offset + 2 + 12 * i + 2
        )
        if field_type not in _TYPE_SIZES:
            raise ValueError(f"unknown TIFF field type {field_type}")
        size = _TYPE_SIZES[field_type] * n_values
        if size > 4:  # up to 4 bytes live inside the entry, which is wiped below
            _zero(tiff, value, size)
    _zero(tiff, offset, 2 + 12 * count + 4)


def _remove_gps_entry(tiff: bytearray) -> bool:
    """Unlink the GPS IFD from IFD0 and wipe it; True if there was one.

    The block keeps its length: the later IFD0 entries and the next-IFD pointer move
    up one slot and the freed 12 bytes are zeroed, so no other offset changes.
    """
    order = {b"II": "<", b"MM": ">"}.get(bytes(tiff[:2]))
    if order is None:
        raise ValueError("not a TIFF block")
    magic, ifd0 = struct.unpack_from(order + "HI", tiff, 2)
    if magic != 42:
        raise ValueError("not a TIFF block")

    (count,) = struct.unpack_from(order + "H", tiff, ifd0)
    first = ifd0 + 2
    end = first + 12 * count + 4  # the entries plus the next-IFD pointer
    if end > len(tiff):
        raise ValueError("IFD0 runs past the TIFF block")

    for entry in range(first, end - 4, 12):
        if struct.unpack_from(order + "H", tiff, entry)[0] == _GPS_INFO:
            break
    else:
        return False

    (gps_ifd,) = struct.unpack_from(order + "I", tiff, entry + 8)
    _zero_ifd(tiff, order, gps_ifd)
    tiff[entry : end - 12] = tiff[entry + 12 : end]
    _zero(tiff, end - 12, 12)
    struct.pack_into(order + "H", tiff, ifd0, count - 1)
    return True


def strip_gps(data: bytes) -> bytes:
    """Return `data` without the EXIF GPS block; anything else comes back unchanged.

    - Not a JPEG (video, PNG, WebP, HEIC, ...): returned as is.
    - A JPEG with no EXIF, or EXIF without GPS: returned as is (the same object).
    - A JPEG with GPS: same length, same bytes, except the GPS IFD is gone.
    - An EXIF segment we cannot parse, or with more than a few GPS pointers (a photo
      has one; a crafted block makes each removal rescan IFD0): dropped whole, because
      we cannot show it holds no position. That also drops its capture time.

    shortcut: JPEG only, and the EXIF IFD0 pointer only. The EXIF thumbnail, XMP
    (``exif:GPS*``), MakerNote and the extra images of a multi-picture file are left
    alone. PNG, WebP and HEIC are not touched either: Pillow can only re-encode those
    (lossy for WebP and HEIC). Upgrade when such uploads carry GPS in practice.
    """
    if not data.startswith(JPEG_MAGIC):
        return data

    out = bytearray(data)
    cuts: list[tuple[int, int]] = []
    changed = False
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte before a marker
            pos += 1
            continue
        if marker in (0xDA, 0xD9):  # scan data or end of image: no more headers
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length
            pos += 2
            continue

        (length,) = struct.unpack_from(">H", data, pos + 2)
        end = pos + 2 + length
        if length < 2 or end > len(data):
            break

        if marker == _APP1 and data[pos + 4 : pos + 10] == _EXIF_HEADER:
            tiff = bytearray(data[pos + 10 : end])
            try:
                removed = False
                # A photo has one GPS pointer. Each removal rescans IFD0, so a crafted
                # block with thousands would cost seconds of CPU: drop it instead.
                for _ in range(MAX_GPS_ENTRIES):
                    if not _remove_gps_entry(tiff):
                        break
                    removed = True
                else:
                    raise ValueError("too many GPS entries")
            except (ValueError, struct.error):
                logger.warning("Dropping an unreadable EXIF segment from an upload")
                cuts.append((pos, end))
            else:
                if removed:
                    out[pos + 10 : end] = tiff
                    changed = True
        pos = end

    for start, end in reversed(cuts):
        del out[start:end]

    return bytes(out) if changed or cuts else data

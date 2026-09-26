"""Export the ingested official posts as a JSONL/CSV archive.

Phase 3 of OFFICIAL_POST_INGESTION.md — the *read* side of the pipeline
Phases 1 and 2 wrote. ``ingest_official_posts`` pulls the operator's X
announcements into ``SocialMediaLink``; this command turns those rows back into
a stable, machine-readable archive::

    python manage.py export_official_posts [--handle askrapidkl] [--since YYYY-MM-DD]
                                            [--until YYYY-MM-DD] [--format jsonl|csv]
                                            [--output PATH|-] [--include-raw]
                                            [--dry-run] [--push-to-hub REPO_ID]

Semantics worth knowing before running it:

* Only automatically ingested rows (``is_automated=True``) are exported. A
  community-submitted link is never part of the operator's archive, however
  much it may look like one.
* ``--since`` / ``--until`` are **inclusive calendar dates in UTC** over
  ``posted_at`` (the post time, not the ingest time) and use the same window
  semantics as the ingest command: ``--since D`` is ``D 00:00:00Z`` and
  ``--until D`` is the whole of D. A row with no known post time falls inside no
  window.
* The columns are the HuggingFace dataset schema — ``post_id``, ``posted_at``,
  ``handle``, ``text``, ``permalink``, plus ``raw_payload`` under
  ``--include-raw`` — and their order is fixed, so exporting unchanged rows
  twice is byte-identical (acceptance criterion 9). ``text`` is the stored
  ``description`` **verbatim**, and ``posted_at`` is that column's own
  ISO-8601 form (``null`` stays ``null``).
* Rows stream out of the database via ``.iterator()``, so an export never
  materialises the table. ``--push-to-hub`` is the one exception:
  ``Dataset.from_dict`` takes the whole record set, not a cursor.
* ``--output -`` (the default) writes rows to stdout and sends the summary line
  to **stderr**, so ``… | jq`` still works. A path writes that file (utf-8) and
  the summary goes to stdout.
* ``--dry-run`` reports how many rows *would* be exported and writes nothing at
  all: no file, no rows, no upload.
* ``--push-to-hub REPO_ID`` is the optional Phase 3b path. It lazy-imports
  ``datasets`` (an install that never pushes does not pay for the Hub client,
  and ``pyproject.toml`` does not hard-depend on it), reads the token from
  ``HF_TOKEN`` — never logged, never printed, never written into the dataset —
  and pushes a **private** dataset.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from incident.models import SocialMediaLink

#: The exported schema, in order. Fixed, so two exports of the same rows are
#: byte-identical and a pushed dataset keeps one stable column set.
EXPORT_COLUMNS: tuple[str, ...] = (
    "post_id",
    "posted_at",
    "handle",
    "text",
    "permalink",
)
#: Appended by ``--include-raw``: the untouched provider payload kept for
#: export fidelity. Large and rarely wanted, hence opt-in.
RAW_COLUMN = "raw_payload"

SUPPORTED_FORMATS: tuple[str, ...] = ("jsonl", "csv")

#: Rows fetched per server-side cursor chunk while streaming. A cursor, not a
#: list, is what keeps a multi-year archive export off the heap.
EXPORT_CHUNK_SIZE = 500


def _csv_cell(value: Any) -> str:
    """Render one value as a CSV cell.

    A dict or list has no flat CSV representation, so a structured value (in
    practice only ``raw_payload``) is JSON-encoded inline. ``sort_keys`` makes
    that encoding canonical, so the same row always produces the same bytes.
    ``None`` is the empty cell, which is how ``csv.writer`` spells it.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


class _RecordWriter:
    """Writes export records as JSONL or CSV into one already-open text stream.

    The CSV variant is a plain :class:`csv.writer`, so quoting of commas,
    quotes and embedded newlines is the stdlib's business — this command
    deliberately has no escaping of its own.
    """

    def __init__(
        self, stream: Any, *, export_format: str, columns: tuple[str, ...]
    ) -> None:
        self._stream = stream
        self._columns = columns
        self._csv = csv.writer(stream) if export_format == "csv" else None
        if self._csv is not None:
            # A CSV archive always carries its header, even when it is empty:
            # the column set is part of the contract.
            self._csv.writerow(columns)

    def write(self, record: dict[str, Any]) -> None:
        if self._csv is not None:
            self._csv.writerow([_csv_cell(record[name]) for name in self._columns])
        else:
            # ensure_ascii=False keeps BM text readable in the archive instead
            # of \uXXXX soup; one object per line, newline-terminated.
            self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def _drain(writer: _RecordWriter, records: Iterable[dict[str, Any]]) -> int:
    """Write every record, returning the count. Never builds a list."""
    written = 0
    for record in records:
        writer.write(record)
        written += 1
    return written


def _row_fields(columns: tuple[str, ...]) -> tuple[str, ...]:
    """The model columns an export actually reads.

    ``raw_payload`` is only selected when it is actually exported — a large
    JSON blob per row should not be read out of the database just to be
    dropped.
    """
    fields = ["post_id", "posted_at", "source_handle", "description", "url"]
    if RAW_COLUMN in columns:
        fields.append(RAW_COLUMN)
    return tuple(fields)


def _summary_line(
    *,
    rows: int,
    export_format: str,
    handles: list[str],
    since: datetime | None,
    until: datetime | None,
    include_raw: bool,
    output: str,
    push_to_hub: str | None,
    dry_run: bool,
) -> str:
    """One greppable ``key=value`` line describing what was, or would be, exported."""
    return (
        f"export rows={rows} format={export_format} "
        f"handle={','.join(handles) or 'all'} "
        f"since={since.date().isoformat() if since else 'none'} "
        f"until={until.date().isoformat() if until else 'none'} "
        f"include_raw={include_raw} output={output} "
        f"push_to_hub={push_to_hub or 'none'} dry_run={dry_run}"
    )


class Command(BaseCommand):
    help = (
        "Export the ingested official posts (is_automated=True) as a JSONL or "
        "CSV archive: post_id, posted_at (ISO-8601), handle, verbatim text, "
        "permalink, plus raw_payload with --include-raw. --output '-' (default) "
        "writes rows to stdout and the summary to stderr; a path writes a file. "
        "--dry-run only reports the row count. --push-to-hub needs the optional "
        "'datasets' package and HF_TOKEN, and always pushes a private dataset."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--handle",
            action="append",
            dest="handles",
            metavar="HANDLE",
            help=(
                "Only export posts attributed to this account, without '@'. "
                "Repeatable; omit for every stored handle."
            ),
        )
        parser.add_argument(
            "--since",
            metavar="YYYY-MM-DD",
            help="Inclusive UTC start date over posted_at (00:00:00Z).",
        )
        parser.add_argument(
            "--until",
            metavar="YYYY-MM-DD",
            help=(
                "Inclusive UTC end date over posted_at — the whole day, up to "
                "23:59:59.999999Z."
            ),
        )
        parser.add_argument(
            "--format",
            choices=SUPPORTED_FORMATS,
            default="jsonl",
            dest="output_format",
            help="Row format (default: jsonl). Unknown values are refused.",
        )
        parser.add_argument(
            "--output",
            metavar="PATH",
            default="-",
            help=(
                "Destination file, or '-' (default) for stdout. Written in "
                "utf-8; the file is overwritten."
            ),
        )
        parser.add_argument(
            "--include-raw",
            action="store_true",
            dest="include_raw",
            help=(
                "Also export the untouched provider payload (raw_payload). "
                "Off by default: it is a large blob and rarely needed."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help=(
                "Report how many rows would be exported and write nothing: no "
                "file, no rows, no hub push."
            ),
        )
        parser.add_argument(
            "--push-to-hub",
            metavar="REPO_ID",
            dest="push_to_hub",
            help=(
                "Also push the records to the HuggingFace dataset REPO_ID, "
                "always private. Needs the optional 'datasets' package and a "
                "HF_TOKEN in the environment."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        handles = [
            handle.strip().lstrip("@")
            for handle in (options.get("handles") or [])
            if handle.strip()
        ]
        since = self._parse_date(options.get("since"), "--since")
        until = self._parse_date(options.get("until"), "--until", end_of_day=True)
        if since is not None and until is not None and until < since:
            raise CommandError(
                f"--until ({options['until']}) is before --since ({options['since']})"
            )

        export_format = options.get("output_format") or "jsonl"
        include_raw = bool(options.get("include_raw"))
        dry_run = bool(options.get("dry_run"))
        output = options.get("output") or "-"
        push_repo = options.get("push_to_hub")
        columns = EXPORT_COLUMNS + ((RAW_COLUMN,) if include_raw else ())
        queryset = self._queryset(handles=handles, since=since, until=until)

        if dry_run:
            # A preview touches nothing: no file, no rows, no upload. Counting
            # is a plain aggregate, so the answer is exact.
            self.stdout.write(
                _summary_line(
                    rows=queryset.count(),
                    export_format=export_format,
                    handles=handles,
                    since=since,
                    until=until,
                    include_raw=include_raw,
                    output=output,
                    push_to_hub=push_repo,
                    dry_run=True,
                )
            )
            return

        # The Hub client wants every record up front (from_dict takes columns,
        # not a cursor), so that path materialises the set — and then reuses it
        # for the file/stdout write instead of querying twice.
        records: list[dict[str, Any]] | None = (
            list(self._iter_records(queryset, columns)) if push_repo else None
        )

        written = self._write(
            self._iter_records(queryset, columns) if records is None else records,
            export_format=export_format,
            columns=columns,
            output=output,
        )

        if push_repo:
            self._push_to_hub(records or [], repo_id=push_repo, columns=columns)

        # Rows on stdout go to stderr instead, so the data stream stays
        # pipeable into another tool.
        summary = _summary_line(
            rows=written,
            export_format=export_format,
            handles=handles,
            since=since,
            until=until,
            include_raw=include_raw,
            output=output,
            push_to_hub=push_repo,
            dry_run=False,
        )
        (self.stderr if output == "-" else self.stdout).write(summary)

    # --- argument resolution -------------------------------------------

    def _parse_date(
        self, raw: str | None, flag: str, *, end_of_day: bool = False
    ) -> datetime | None:
        """Parse ``YYYY-MM-DD`` into an aware UTC bound.

        ``end_of_day`` takes the last microsecond of the day, so ``--until D``
        covers the whole of D. The bound stays aware on purpose: the project
        runs ``USE_TZ = False``, and Django's adapter converts the aware value
        into the storage frame when it builds the query, so a UTC calendar day
        is what gets compared either way.
        """
        if not raw:
            return None
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            raise CommandError(f"{flag} must be YYYY-MM-DD (got {raw!r})") from None
        moment = time(23, 59, 59, 999999) if end_of_day else time(0, 0)
        return datetime.combine(parsed, moment, tzinfo=UTC)

    # --- query ----------------------------------------------------------

    def _queryset(
        self, *, handles: list[str], since: datetime | None, until: datetime | None
    ):
        """The exportable rows: automated posts, narrowed and totally ordered.

        Ordering is ``posted_at`` then ``post_id`` (both nulls last, so rows
        with no known post time trail the archive), with ``id`` closing the last
        tie — without it, rows sharing a null ``posted_at`` *and* a null
        ``post_id`` could come back in any order, and "same input → same
        output" would be luck rather than a guarantee.
        """
        queryset = SocialMediaLink.objects.filter(is_automated=True)
        if handles:
            queryset = queryset.filter(source_handle__in=handles)
        if since is not None:
            queryset = queryset.filter(posted_at__gte=since)
        if until is not None:
            queryset = queryset.filter(posted_at__lte=until)
        return queryset.order_by(
            F("posted_at").asc(nulls_last=True),
            F("post_id").asc(nulls_last=True),
            "id",
        )

    def _iter_records(
        self, queryset, columns: tuple[str, ...]
    ) -> Iterator[dict[str, Any]]:
        """Stream one export record per row, holding one chunk at a time.

        ``raw_payload`` is only fetched when it is actually exported — a big
        JSON blob per row should not be read just to be dropped.
        """
        fields = _row_fields(columns)
        rows = queryset.only(*fields).iterator(chunk_size=EXPORT_CHUNK_SIZE)
        for row in rows:
            record = {
                "post_id": row.post_id,
                "posted_at": (
                    row.posted_at.isoformat() if row.posted_at is not None else None
                ),
                "handle": row.source_handle,
                # Verbatim BM post text, byte for byte as ingested.
                "text": row.description,
                "permalink": row.url,
            }
            if RAW_COLUMN in columns:
                record[RAW_COLUMN] = row.raw_payload
            yield record

    # --- output ---------------------------------------------------------

    def _write(
        self,
        records: Iterable[dict[str, Any]],
        *,
        export_format: str,
        columns: tuple[str, ...],
        output: str,
    ) -> int:
        """Write the records to stdout or to a file; return how many."""
        if output == "-":
            return _drain(
                _RecordWriter(
                    self.stdout, export_format=export_format, columns=columns
                ),
                records,
            )
        try:
            # newline="" is what the csv docs require (and is harmless for
            # JSONL, whose newlines are written explicitly).
            with Path(output).open("w", encoding="utf-8", newline="") as stream:
                return _drain(
                    _RecordWriter(stream, export_format=export_format, columns=columns),
                    records,
                )
        except OSError as exc:
            # An undeliverable destination is a command failure, not a
            # traceback — the same treatment the ingest command gives a bad
            # fixture path.
            raise CommandError(
                f"--output {output} could not be written ({type(exc).__name__})"
            ) from None

    def _push_to_hub(
        self, records: list[dict[str, Any]], *, repo_id: str, columns: tuple[str, ...]
    ) -> None:
        """Push the records to a **private** HuggingFace dataset.

        ``private=True`` is unconditional: tweet content redistributed on the
        Hub is outside X's terms, so publication is never the default of a
        bare command invocation. The token is read from the environment and
        handed straight to the client — it is never logged, printed or stored.
        """
        dataset_class = self._load_datasets()
        dataset = dataset_class.from_dict(
            {name: [record[name] for record in records] for name in columns}
        )
        dataset.push_to_hub(repo_id, token=os.environ.get("HF_TOKEN"), private=True)

    def _load_datasets(self) -> Any:
        """Import the optional ``datasets`` package, or say how to get it.

        The import lives inside the flag's own path so an install that never
        pushes neither pays for nor hard-depends on the Hub client, and a
        missing package is an actionable message rather than an ImportError
        traceback.
        """
        try:
            from datasets import Dataset
        except ImportError:
            raise CommandError(
                "--push-to-hub requires the 'datasets' package, which is not "
                "installed; install it (`pip install datasets`, or add it to "
                "pyproject.toml) and re-run with HF_TOKEN set in the environment"
            ) from None
        return Dataset

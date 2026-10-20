# Django 5.2 Upgrade — record

Completed 2026-08-18: Django 4.2.20 → 5.2.17 (`"django==5.2.*"` in `pyproject.toml`; the
pin lives in `requirements*.lock`, see [techstack.md](techstack.md)). No application code
changes were needed beyond the items below.

- **Migrations:** `advanced_filters.0004_alter_advancedfilter_id` (third-party app, shipped
  in `advanced_filters_migrations/`; `BigAutoField`) and `common.0018_alter_media_file`
  (re-declares `ImgurField` storage/upload config; no schema change).
- **Strawberry filters:** `FilterLookup[str]` → `StrFilterLookup` in the `operation` and
  `spotting` filter modules, which removed the `DuplicatedTypeName` warnings. The standing
  rule is in [docs/STRAWBERRY_MIGRATION.md](docs/STRAWBERRY_MIGRATION.md).
- **Already compatible:** `DEFAULT_AUTO_FIELD = BigAutoField` was set; no deprecated imports
  (`force_text`, `ugettext`); the async ORM calls in use (`acreate`, `aget`, `asave`,
  `async for`) are unchanged; `TextChoicesField` (django-choices-field) needed nothing.
- **Expected `check --deploy` output on dev:** warnings for `DEBUG=True` and no HTTPS.

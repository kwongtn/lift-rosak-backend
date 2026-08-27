# AGENTS.md — rosak_backend

Django 5.2 + Strawberry GraphQL backend for the MLPTF/LRT community platform.
**This repo is backend-only.** The Angular SPA at `community.mlptf.org.my` lives in a
separate repository and is only a consumer of `POST /graphql/` — never add frontend
code here.

---

## ⚡ Quick Commands

Everything runs through Docker Compose — it is the only path that provides PostGIS,
Redis and nginx together. Run `manage.py` inside the `app` service, never on the host.

```bash
# Dev stack (nginx :8000 → granian :8001, db, redis, celeryworker, celerybeat)
docker compose up --build          # add -d to detach
docker compose logs -f app         # tail the API
docker compose down                # stop

# Django management (prefix everything)
docker compose exec app python manage.py <cmd>
docker compose exec app python manage.py check          # WSGI stack does NOT run checks
docker compose exec app python manage.py shell_plus     # django-extensions
docker compose exec app python manage.py createsuperuser

# Database migrations
docker compose exec app python manage.py makemigrations
docker compose exec app python manage.py migrate
docker compose exec app python manage.py makemigrations --check --dry-run  # CI-style gate
./dev_permissioner.sh              # ALWAYS after makemigrations — files are root-owned

# Tests — single-run, no watch mode
docker compose exec app python manage.py test --parallel --keepdb
docker compose exec app python manage.py test spotting.tests --keepdb   # one app

# Lint & format (ruff is the enforced gate; run before every handoff)
ruff check . --fix
ruff format .
pre-commit run --all-files

# Celery (already running in compose; for manual invocation)
docker compose exec app celery -A rosak.celery_app worker -l INFO -c 2
docker compose exec app celery -A rosak.celery_app beat -l INFO
```

**Testing state (as of August 2026):** Full test suite passes with **180 tests** after
the Strawberry GraphQL migration. `tests.py` was previously 0 bytes in `common`,
`generic`, `mlptf`, `operation` and `reporting`; migration added 50+ new unit tests
across all phases. No pytest/tox/coverage yet. **`ruff check` + `manage.py check` +
`makemigrations --check` + full test suite are the verification gate.** If you touch a
module, add tests for new behavior in the same change.

---

## 🏛️ Architecture & Component Pointer

Django 4.2 on PostGIS (GeoDjango), exposing a **single async GraphQL endpoint** built
with **Strawberry GraphQL 0.323.2** (strawberry-graphql-django 0.82.1, migrated from
`UNSET` to `strawberry.Maybe[T]` pattern in August 2026) — the root `Query`/`Mutation`
are assembled by _multiple inheritance_ in [rosak/schema.py](rosak/schema.py), so there
is no routing layer. Auth is Firebase bearer-token → lazily `get_or_create`'d
`common.User` in [rosak/context.py](rosak/context.py), with per-request DataLoaders and
three Strawberry permission classes (`IsLoggedIn` / `IsAdmin` / `IsRecaptcha`). Async
work is Celery + Redis with **all six periodic jobs declared centrally** in
[rosak/celery.py](rosak/celery.py); served by Granian ASGI behind nginx.

**Do not guess at component interfaces.** Read the docs first:

- **[docs/APPS.md](docs/APPS.md)** — component registry, topology diagram, the cyclic
  dependency graph, the beat-schedule table, and a **Known Defects & Traps** table.
  Read the traps table before debugging anything that looks broken; it probably is,
  and is already catalogued.
- **[docs/components/](docs/components/)** — one doc per app
  (`operation`, `common`, `spotting`, `incident`, `chartography`, `telegram_provider`,
  `generic`, `reporting`, `mlptf`), each carrying its real interface, dependencies and
  **designed extension points**.

Orientation: `operation` is the reference-data hub everything FKs into; `common` is the
substrate (identity, media pipeline, `get_trends()` analytics); `generic` is a
table-less shared kernel that contributes zero migrations.

---

## 📏 Non-Negotiable Code Conventions

**Module boundaries**

- [tach.yml](tach.yml) declares the allowed cross-app import graph. Consult it before
  adding any import between apps; `tach` is not installed by default (`uvx tach check`).
- The graph is already heavily cyclic. Break new cycles with **lazy string model
  references** (`"operation.Vehicle"`) or function-local imports — never a new
  module-level cross-app import.
- `django_cleanup` must stay **last** in `INSTALLED_APPS`.

**GraphQL / Strawberry**

- **Migration status (August 2026):** Migrated to Strawberry GraphQL 0.323.2 with
  `strawberry.Maybe[T]` pattern (replaces deprecated `UNSET`). See
  [docs/STRAWBERRY_MIGRATION.md](docs/STRAWBERRY_MIGRATION.md) for tri-state semantics
  and behavioral parity verification.
- New root fields go on the per-app `*Scalars` / `*Mutations` mixin, not on `rosak/schema.py`.
- New DataLoaders: add one key to the app's `*ContextLoaders` dict and register it in
  `rosak/context.py`. Resolvers that fan out to related rows **must** use a loader —
  the optimizer cannot see manual re-fetches.
- Enum fields must use `TextChoicesField` (django-choices-field). A plain
  `TextField(choices=...)` renders as `String` in the schema, not an enum.
- Resolvers are `async`; never call the sync ORM from one without `sync_to_async`.
- Optional input fields: use `strawberry.Maybe[T | None] = None` for tri-state
  (UNSET/Some(value)/Some(None)). Check with `if input.field:` then access
  `input.field.value`.

**Database & migrations**

- PostGIS is required — geometry fields use `django.contrib.gis`.
- Never edit an applied migration. Add a new one.
- Data migrations must be reversible or explicitly declare `migrations.RunPython.noop`.
- Run `./dev_permissioner.sh` after any container-generated migration.

**Celery**

- New periodic work goes in `rosak/celery.py`'s `beat_schedule` — **never** a local
  schedule. `autodiscover_tasks()` means a new `tasks.py` needs no registration.
- Retries must be bounded. Unbounded retry-with-sleep loops pin a worker (see
  `infinite_retry_on_error` in the traps table).

**Error handling & typing**

- **Never use bare `assert` for validation or request guarding.** It is stripped under
  `python -O` and surfaces as a 500, not a validation error. Raise an explicit
  exception or a Strawberry error. Existing `assert`s in `incident` and `chartography`
  are known defects, not precedent to copy.
- Type all new function signatures; `mypy` is configured with the Strawberry plugin
  ([mypi.ini](mypi.ini)).
- Line length 88, `E501` ignored, max mccabe complexity 18 ([.ruff.toml](.ruff.toml)).
  Ruff is authoritative — the stale black/flake8 hints in `.vscode/settings.json` are not.

**Local-vs-prod gotcha:** `DEBUG=True` swaps the Redis cache for `DummyCache` and
disables GraphQL introspection guarding. Cache-related bugs will not reproduce locally.

---

## 🔄 Workflow & Execution Rules

**Explore → Plan → Code → Verify.** For any change touching more than one file:

1. **Explore** — read [docs/APPS.md](docs/APPS.md) and the relevant
   `docs/components/*.md` before opening source. Check the traps table.
2. **Plan** — state the file list, the migration impact, and any `tach.yml` boundary
   the change crosses. Get agreement _before_ editing. Do not start multi-file edits
   from an implicit plan.
3. **Code** — smallest change that satisfies the request. Prefer the documented
   extension point over new plumbing.
4. **Verify** — never declare a task complete without running:
   `ruff check . --fix && ruff format . && docker compose exec app python manage.py check`
   plus `makemigrations --check --dry-run` if models changed, and the relevant tests.
   Report failures with their output; never claim a skipped step passed.

**Context hygiene** — run `/clear` between unrelated features. This codebase has nine
apps with a cyclic import graph; stale context from a previous app is a reliable source
of wrong cross-app assumptions.

**Secrets** — `secrets.env` and `secrets.dev.env` are local-only. Never commit
credentials, and never echo their contents into logs or output.

**Git commits** — history is conventional-commits (`feat(incident): …`,
`fix(ci): …`). Commit at logical checkpoints — one concern per commit — so the history
reads chronologically and the working tree is never left full of uncommitted changes;
push only when asked. Any AI-assisted commit must append a `Co-authored-by:` trailer naming the agent **and**
the model used, e.g. `Co-authored-by: opencode (opencode-go/deepseek-v4-flash)
<noreply@opencode.ai>` or `Co-authored-by: Claude Code (claude-sonnet-4-5)
<noreply@anthropic.com>`. Never attribute AI work to a human co-author.

---

## 📝 Documentation Maintenance Rules

### MISTAKES.md

- **Location**: Repo root (`MISTAKES.md`)
- **Purpose**: Catalog of known defects, traps, and past mistakes so future agents don't repeat them
- **Update trigger**: When you discover a new defect/trap, or when a documented trap is fixed
- **Format**:
  ```markdown
  ## [YYYY-MM-DD] Component: Brief Title

  **Problem**: What went wrong
  **Root Cause**: Why it happened
  **Fix**: What was done (commit ref if applicable)
  **Prevention**: How to avoid in future
  ```

### Progress Documentation (docs/progress/)

- **Structure**: `docs/progress/<yyyy>/<mm>/<dd>.md` + `SUMMARY.md` at month/year levels
- **Update trigger**: When implementing features, fixing bugs, or resolving TODOs
- **Content**: Grouped by module/feature, with commit references
- **Cleanup**: Remove completed items from "Suggested Features", "TODO", "Potential Feature Opportunities" sections in component docs
- **Main docs stay clean**: Component docs only show _current_ opportunities, not history

### Workflow Integration

1. After any verified task completion → check if it resolves a MISTAKES entry or completes a TODO
2. If yes → append to today's `docs/progress/<yyyy>/<mm>/<dd>.md`
3. Update monthly/yearly SUMMARY.md
4. Remove from component doc's opportunity/TODO sections
5. If it was a documented trap → update MISTAKES.md with fix reference

# CLAUDE.md — rosak_backend

Django 4.2 + Strawberry GraphQL backend for the MLPTF/LRT community platform.
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

**Honest state of testing:** `tests.py` is 0 bytes in `common`, `generic`, `mlptf`,
`operation` and `reporting`; there is no pytest, tox or coverage in the lockfiles. The
test command above works but currently asserts nothing. **`ruff check` +
`manage.py check` + `makemigrations --check` are the real verification gate today.**
If you touch a module, add the first real test for it in the same change.

---

## 🏛️ Architecture & Component Pointer

Django 4.2 on PostGIS (GeoDjango), exposing a **single async GraphQL endpoint** built
with Strawberry — the root `Query`/`Mutation` are assembled by *multiple inheritance* in
[rosak/schema.py](rosak/schema.py), so there is no routing layer. Auth is Firebase
bearer-token → lazily `get_or_create`'d `common.User` in [rosak/context.py](rosak/context.py),
with per-request DataLoaders and three Strawberry permission classes
(`IsLoggedIn` / `IsAdmin` / `IsRecaptcha`). Async work is Celery + Redis with **all six
periodic jobs declared centrally** in [rosak/celery.py](rosak/celery.py); served by
Granian ASGI behind nginx.

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
- New root fields go on the per-app `*Scalars` / `*Mutations` mixin, not on `rosak/schema.py`.
- New DataLoaders: add one key to the app's `*ContextLoaders` dict and register it in
  `rosak/context.py`. Resolvers that fan out to related rows **must** use a loader —
  the optimizer cannot see manual re-fetches.
- Enum fields must use `TextChoicesField` (django-choices-field). A plain
  `TextField(choices=...)` renders as `String` in the schema, not an enum.
- Resolvers are `async`; never call the sync ORM from one without `sync_to_async`.

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
   the change crosses. Get agreement *before* editing. Do not start multi-file edits
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

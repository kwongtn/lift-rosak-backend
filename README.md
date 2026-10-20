# rosak_backend

Backend for the rosak project — Malaysian public transport community platform.
Django + Strawberry GraphQL (async) on PostGIS, Celery + Valkey for async work, served by
Granian behind nginx (versions: [techstack.md](techstack.md)). The Angular SPA lives in the
sibling `rosak_firebase` repo and consumes `POST /graphql/`.

## Quick start

Prerequisites: Docker Compose, a local `secrets.dev.env`, and the Firebase service-account
JSON that `docker-compose.yml` mounts from `~/.firebase/`.

```bash
docker compose up --build -d     # web (nginx) :8000 → app (granian) :8001, db, timescaledb, valkey, celery
docker compose exec app python manage.py check
```

`run_app.sh` runs `migrate` on startup. All other commands (tests, migrations, lint,
Celery) are in [AGENTS.md](AGENTS.md#-quick-commands).

## Calendar incident workflow

Community-reported service disruptions with an author/admin approval flow:

```
DRAFT ──submitCalendarIncident──▶ PENDING_APPROVAL ──approveCalendarIncident──▶ LIVE
  │                                        │
  │                                        └─rejectCalendarIncident(reason)──▶ REJECTED
  └─deleteCalendarIncident (soft delete)

LIVE + edit by non-admin ─▶ new DRAFT revision (parent_incident FK)
approve(revision)         ─▶ atomic merge into parent (votes preserved), revision hard-deleted
```

- **Statuses:** `incident/enums.py`. `createCalendarIncident` makes a DRAFT for users and
  LIVE for admins; `submitCalendarIncident` moves an author's (or admin's) DRAFT into the
  approval queue.
- **Purge** (`incident/tasks.py`, daily beat jobs): REJECTED rows hard-deleted after 30
  days, soft-deleted rows after 90 days. Hard deletes cascade votes via the
  `GenericRelation` on CalendarIncident/Chronology.
- **Optimistic concurrency:** updates accept the client's `version`; a mismatch raises a
  concurrency error instead of overwriting.
- **Admin-only:** the approval queue (`pendingCalendarIncidents`), link triage
  (`socialMediaLinks`) and the approve / reject / mark-completed mutations.
- **Full API** (queries, mutations, arguments): `rosak/tests/snapshots/schema.graphql` and
  [docs/components/incident.md](docs/components/incident.md).

### Incident extraction (`extractDataFromUrl`)

Proxies the Firebase callable `extractIncidentData` (Gemini extraction), forwarding the
caller's Firebase ID token. The function enforces the rate limit (20 requests/hour/user,
Firestore-backed, per UTC hour bucket); the backend surfaces its resource-exhausted error as
a GraphQL error.

| Variable                    | Consumer  | Purpose                                            |
| --------------------------- | --------- | -------------------------------------------------- |
| `EXTRACT_INCIDENT_DATA_URL` | backend   | URL of the `extractIncidentData` Firebase callable |
| `GEMINI_API_KEY`            | functions | Gemini API key for extraction                      |
| `FETCHER_STRATEGY`          | functions | `cheerio` (default) or `puppeteer` page fetcher    |

## Docs

- [AGENTS.md](AGENTS.md) — commands, conventions, doc-maintenance rules
- [techstack.md](techstack.md) — stack inventory
- [docs/APPS.md](docs/APPS.md) — component registry, topology, traps table
- [docs/components/](docs/components/) — per-app interfaces and extension points
- [MISTAKES.md](MISTAKES.md) — catalogued defects and test-runner caveats

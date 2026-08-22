# rosak_backend

Backend for the rosak project — Malaysian public transport community platform.
Django 4.2 + Strawberry GraphQL (async) on PostGIS, Celery + Redis for async work,
served by Granian behind nginx. The Angular SPA lives in the sibling `rosak_firebase`
repo and consumes `POST /graphql/`.

## Quick start

```bash
docker compose up --build -d     # nginx :8000 → granian :8001, db (PostGIS), redis, celery
docker compose exec app python manage.py migrate
docker compose exec app python manage.py check
```

## Calendar incident reporting system

Community-reported service disruptions with an author/admin workflow:

```
DRAFT ──submitCalendarIncident──▶ PENDING_APPROVAL ──approveCalendarIncident──▶ LIVE
  │                                        │
  │                                        └─rejectCalendarIncident(reason)──▶ REJECTED
  └─deleteCalendarIncident (soft delete, 90-day retention)

LIVE + edit by non-admin ─▶ new DRAFT revision (parent_incident FK)
approve(revision)         ─▶ atomic merge into parent (votes preserved), revision hard-deleted
```

- **Statuses:** DRAFT → PENDING_APPROVAL → LIVE / REJECTED (`incident/enums.py`).
- **Intake:** `createCalendarIncident` creates a DRAFT for users and LIVE for admins;
  `submitCalendarIncident(id)` moves an author's (or admin's) DRAFT into the approval queue.
  The frontend form chains create → submit automatically for non-admins.
- **Purge tasks** (`incident/tasks.py`, beat-scheduled daily in `rosak/celery.py`):
  REJECTED rows hard-deleted after 30 days; soft-deleted rows after 90 days. Hard deletes
  cascade votes via the `GenericRelation` on CalendarIncident/Chronology.
- **Optimistic concurrency:** updates accept the client's `version`; mismatch raises a
  concurrency error instead of clobbering.

### GraphQL API (root fields added by the incident feature)

Queries:
- `calendarIncidents(filter, order)` — public list (LIVE only); scalars expose
  `voteScore`, `voteBreakdown { upvotes downvotes }`, `userVote` via DataLoaders.
- `calendarIncidentsBySeverityCount(start, end, groupBy)` — chart aggregation (DAY/MONTH).
- `pendingCalendarIncidents(search)` — admin-only approval queue (title/brief/details/
  chronology source-url search, oldest first).
- `socialMediaLinks(search, categoryId, completed)` — admin-only triage queue, newest first.
- `calendarIncidentCategories` — category list for filters.

Mutations:
- `createCalendarIncident(input)` → `{ ok, id }` (users: DRAFT; admins: LIVE)
- `updateCalendarIncident(id, input)` — edits DRAFT in place; editing LIVE creates a revision
- `submitCalendarIncident(id)` — DRAFT → PENDING_APPROVAL (author or admin)
- `approveCalendarIncident(id)` — PENDING → LIVE, or merges a revision into its parent
- `rejectCalendarIncident(id, reason)` — DRAFT/PENDING → REJECTED with persisted reason
- `deleteCalendarIncident(id)` — soft delete (authors: own drafts; admins: anything)
- `createChronology / updateChronology / approveChronology / reorderChronology / deleteChronology`
- `upvote / downvote / removeVote` — idempotent vote mutations over the generic Vote model
- `submitSocialMediaLink(input)` — "just dumping" or incident-tagged link submissions
- `markSocialMediaLinkCompleted(linkId)` — records the admin who completed it
- `extractDataFromUrl(url)` — proxies the Firebase callable `extractIncidentData`
  (Gemini extraction). Forwards the caller's Firebase ID token so the function-side
  rate limit (20 requests/hour/user, Firestore-backed) stays authoritative.

### Console (admin) pages

Frontend routes `/console/insiden/pending` (approval queue) and
`/console/insiden/links` (link triage), guarded by the Firebase `admin` custom claim
(`adminOnlyGuard`). Backend counterparts are the admin-only queries above plus
the approve/reject/mark-completed mutations.

### Deployment notes

Environment variables:

| Variable | Consumer | Purpose |
|---|---|---|
| `EXTRACT_INCIDENT_DATA_URL` | backend | URL of the `extractIncidentData` Firebase callable |
| `GEMINI_API_KEY` | functions | Gemini API key for extraction |
| `FETCHER_STRATEGY` | functions | `cheerio` (default) or `puppeteer` page fetcher |

Firebase Functions rate limiting is Firestore-backed per user per UTC hour bucket;
the backend only forwards the caller's token and surfaces the function's
resource-exhausted error as a GraphQL error.

### Tests

```bash
docker compose exec app python -m pytest tests/incident -q          # incident suite
docker compose exec app python -m pytest tests/incident -q \
  --cov=incident --cov-report=term                                   # coverage gate (91%)
```

`.coveragerc` omits test modules and migrations so the gate measures application code.
Unit tests cover services, mutation resolvers, DataLoaders, model validation, schema
assembly, purge tasks, and the rate-limit proxy contract; `test_e2e_workflows.py`
exercises complete user journeys through the real submit path.

## Docs

- [docs/APPS.md](docs/APPS.md) — component registry, topology, traps table
- [docs/components/](docs/components/) — per-app interfaces and extension points

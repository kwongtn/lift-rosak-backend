# Yearly Summary - 2026

Total commits: 187 non-merge to Oct 20 (Aug 72, Sep 100, Oct 1–20 15; `git log --no-merges`, counted 2026-10-21). Some September entries have no daily log; the September summary marks them.

## Monthly Breakdown

### 2026-10 - [October summary](10/SUMMARY.md) (15 commits to Oct 20)

- Social-link threads become an ordered nested tree (migration 0031 failed on staging and was fixed in the same change). `lastWeekOnly` closes at midnight.
- Vote mutations return vote state; network and multi-line status history; official posts auto-publish.
- Front-page pulse N+1 fixed; `lastSpottedAt` tiebreaker; `/spot` exact matching.
- Docs squash to current state; `updateUser` null guard, Telegram settings coercion, `report_spotting_today` digest date fixed and the digest sends again after a nightly DISTINCT ON crash; lines may share a Telegram channel (Oct 21).
- Frontend audit fix pass, backend side (Oct 21): `media(id)` query; anonymous spottings hide their location, profile rows, counts and photo uploader from everyone but the reporter and admins; lossless EXIF GPS strip from JPEG, with every image accepted (HEIC and other formats are stored as received, by the owner's choice); one-GROUP-BY year counts; per-viewer cache Vary on GraphQL GETs. Suite at 601 tests.
- Frontend audit feature pass, backend side (Oct 22): `calendarIncidents` filters (`activeNow`, `upcomingWithinDays`, `lines`, `stations`, `status`); `Asset.status` enum; `daysAgo` on the status-history queries and `lineStatusWeekProfile`; web push subscriptions with MAJOR-incident alerts through Firebase Cloud Messaging; per-month LIVE severity aggregate, medias paging tie-break, `Asset.station`. Suite at 686 tests.
- Daily digest (Oct 24): `report_spotting_today` fires at 03:01 instead of 00:00 and covers the 27-hour service day `[D 03:01, D+1 03:01)` by submission time (`Event.created`); `/spotting_today` unchanged. Suite at 692 tests.
- Kuala Lumpur time sweep (Oct 24): aware client datetimes are normalised to naive KL at the incident boundary, so console resaves keep pending chronology states; official-post CLI `--since` / `--until` are KL days; `get_trends` resolves its end per call. Suite at 725 tests.
- Logged days: [01](10/01.md), [03](10/03.md), [08](10/08.md), [19](10/19.md), [20](10/20.md), [21](10/21.md), [22](10/22.md), [24](10/24.md).

### 2026-09 - [September summary](09/SUMMARY.md) (100 commits)

- Official-post pipeline: ingestion, scheduled task, admin notify and approval, export, X webhook receiver. Polling made opt-in.
- Social-link feed: `occurred_at` event time, threads, `lastWeekOnly`/`alignPageToDay`, `HIDDEN` moderation, `isAutomated`, entity decoding.
- Agency/SocMedAccount registry replaces `OFFICIAL_POST_HANDLES`.
- Line status: `PassengerStatus`, `LineStatusReport`, consolidated pulse, feed submit and votes, hourly history.
- Telegram `/approve`, photo/video auto-attach, `/spotting_today` 3am cutoff.
- Python 3.13, dependency refresh, celerybeat credential mount fixed.
- Logged days: [12](09/12.md), [13](09/13.md), [15](09/15.md), [16](09/16.md), [22](09/22.md), [23](09/23.md), [24](09/24.md), [26](09/26.md), [28](09/28.md), [30](09/30.md).

### 2026-08 - [August summary](08/SUMMARY.md) (72 commits)

- Incident module built out: Vote and SocialMediaLink models, CRUD and submit mutations, console queue, end-to-end tests.
- GraphQL moved from `UNSET` to `strawberry.Maybe[T]` in four phases; schema snapshot baseline added.
- Django 5.2 upgrade, governed outbound Telegram egress, NSFW moderation re-enabled, `CLAUDE.md` renamed to `AGENTS.md`.
- Logged days: [06](08/06.md), [14](08/14.md), [17](08/17.md), [18](08/18.md), [19](08/19.md), [21](08/21.md), [22](08/22.md), [24](08/24.md), [25](08/25.md), [26](08/26.md), [27](08/27.md) (no commits).

## Key Milestones (2026)

### Major Features & Refactors

- 2026-08-18: Django 5.2 upgrade. ([18](08/18.md))
- 2026-08-19: GraphQL `UNSET` to `Maybe[T]` migration. ([19](08/19.md))
- 2026-08-22: incident mutations, submit flow and end-to-end tests. ([22](08/22.md))
- 2026-08-25: outbound Telegram routed through one governed egress path. ([25](08/25.md))
- 2026-09-12: video in the temporary media pipeline. ([12](09/12.md))
- 2026-09-22: community front-page backend: line status reports, pulse, canonical URLs, feed submit and votes. ([22](09/22.md))
- 2026-09-24: Python 3.13 runtime. ([24](09/24.md))
- 2026-09-26: official-post ingestion foundation (`c23e7bc`). ([26](09/26.md))
- 2026-09-28: X webhook receiver; Agency/SocMedAccount registry. ([28](09/28.md))
- 2026-09-30: `occurred_at` event time and thread grouping. ([30](09/30.md))
- 2026-10-01: nested social-link tree; migration 0031 fix. ([01](10/01.md))
- 2026-10-03: network and multi-line status history. ([03](10/03.md))
- 2026-10-08: official posts auto-publish. ([08](10/08.md))
- 2026-10-20: `Vehicle.lastSpottedAt` tiebreaker. ([20](10/20.md))
- 2026-10-22: web push subscriptions and MAJOR-incident alerts; incident window, line and station filters; `Asset.status`; typical-week status profile. ([22](10/22.md))
- 2026-10-24: daily digest at 03:01 over the 27-hour service day, by submission time; backend timings anchored to Kuala Lumpur time. ([24](10/24.md))

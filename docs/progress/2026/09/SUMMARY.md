# Monthly Summary - September 2026

Total commits: 18

## Commit Type Distribution

- feat: 12
- fix: 3
- test: 2
- chore: 1

## By Module/Feature

### Incident (6 commits)

- **67a830c** [feat](incident): complete insiden reporting backend
- **b9bd6fd** [feat](incident): add public publicSocialMediaLinks GraphQL query with line filter
- **1533846** [feat](incident): allow admin to fully edit SocialMediaLink before completion
- **990d89c** [feat](incident): expose status on CalendarIncidentScalar
- **f1b89ec** [fix](incident): coerce null details/title/brief to empty string for CalendarIncident
- **799ea77** [fix](incident): coerce null title to empty string for SocialMediaLink

### Common (6 commits)

- **010428c** [test](common): cover video pipeline and bounded cleanup
- **82addcc** [feat](common): support video in temporary media pipeline
- **a9f1067** [feat](common): hold AWAITING_REVIEW media from auto-conversion
- **511afaa** [feat](common): expose media caption/duration/type on MediaScalar
- **9ba0763** [feat](common): add caption/duration to Media and widen content_type
- **a531e51** [feat](common): add AWAITING_REVIEW temporary media status

### Telegram (4 commits)

- **82e5c3f** [test](telegram): cover media upload + /approve
- **ed9c461** [feat](telegram): register media handler and /approve command
- **ea49424** [feat](telegram): add /approve for reviewed media
- **a82de20** [feat](telegram): auto-attach incoming photo/video to latest spotting

### Ci (1 commits)

- **6fd0d1a** [fix](ci): publish full commit hash for version endpoint

### Rosak (1 commits)

- **0ff57ec** [chore](rosak): refresh GraphQL schema snapshot for media fields

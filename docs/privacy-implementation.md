# Privacy Implementation — Public Profiles

## Schema

- `common.models.User.spotting_data_public` — `BooleanField`, default `False` (strictly
  opt-in); gates visibility of historical spottings on public profiles. Added in
  `common/migrations/0019_user_spotting_data_public_userjejaktransaction.py`.
- `UserScalar.spottingDataPublic: Boolean!` exposes the flag.

## GraphQL

- **`publicUser(id: ID!): UserScalar`** — no permission class (public). `id` is the
  user's **Firebase UID** (`User.firebase_id`), not the database pk. Returns `null` when
  not found.
- **`UserScalar.spottings: [EventScalar!]`** — enforced in the resolver
  (`common/schema/scalars.py`):
  - owner (authenticated user viewing own profile): full list
  - non-owner + `spotting_data_public=True`: full list
  - non-owner + `spotting_data_public=False`: `null` (`null` = private, `[]` = no data)
- **`updateUser(input: UserInput!)`** — `IsLoggedIn`, updates only the caller.
  `UserInput.spotting_data_public` is `Maybe[bool | None] = UNSET`; omitted leaves the
  stored value unchanged (tri-state rules: [STRAWBERRY_MIGRATION.md](STRAWBERRY_MIGRATION.md)).

## Contract

| Tier                                           | Fields                                                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Always public                                  | `nickname`, `shortId` (first 8 chars of the Firebase UID), `spottingsCount`, `mediaCount`, `spottingTrends`, `withMostEntries`, `favouriteVehicles` |
| Opt-in (`spotting_data_public=true`, or owner) | `spottings` — date, notes, vehicle details, media count, status                                                                   |
| Never exposed                                  | email; full Firebase UID (`firebase_id` is `IsAdmin`-only)                                                                        |

## Notes

- Privacy is field-level, in the resolver; the per-user DataLoader
  (`spottings_from_user_loader`) is preserved. The caller comes from `info.context.user`.
- Tests in `common/tests.py`: `UserPrivacyTests` (default private; owner / public /
  private access), `SpottingDataPublicMigrationTests`, `TestUserInput` and
  `TestUpdateUserMutation` (omitted / null / true).

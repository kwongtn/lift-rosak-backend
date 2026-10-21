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
  - non-owner + `spotting_data_public=True`: the list **without anonymous spottings**
    (admins keep them)
  - non-owner + `spotting_data_public=False`: `null` (`null` = private, `[]` = no data)
- **`updateUser(input: UserInput!)`** — `IsLoggedIn`, updates only the caller.
  `UserInput.spotting_data_public` is `Maybe[bool] = UNSET` (the column is `NOT NULL`);
  omitted leaves the stored value unchanged and an explicit `null` is a validation error
  (tri-state rules: [STRAWBERRY_MIGRATION.md](STRAWBERRY_MIGRATION.md)).

## Contract

| Tier                                           | Fields                                                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Always public                                  | `nickname`, `shortId` (first 8 chars of the Firebase UID), `mediaCount`, and `spottingsCount`, `spottingTrends`, `withMostEntries`, `favouriteVehicles` without anonymous spottings (`mediaCount` also leaves out the user's photos on them) |
| Opt-in (`spotting_data_public=true`, or owner) | `spottings` — date, notes, vehicle details, media count, status                                                                   |
| Owner and admins only                          | the anonymous spottings in `spottings`, and in the four figures above; the `uploader` of a photo on an anonymous spotting (the photo itself is public) |
| Never exposed                                  | email; full Firebase UID (`firebase_id` is `IsAdmin`-only)                                                                        |

## Anonymous spottings

`Event.is_anonymous` hides the reporter (`EventScalar.reporter` is `null`) and the
event's GPS position. `EventScalar.location` resolves to `null` unless the viewer is the
event's reporter or an admin (Firebase `admin` claim), on every path that returns an
`EventScalar`: `events`, `Vehicle.spottings`, `UserScalar.spottings` and the `addEvent`
payload. Non-anonymous events show their position to everyone. See
`spotting.schema.resolvers.viewer_can_see_location` and
[components/spotting.md](components/spotting.md).

**Profiles.** An anonymous spotting is also kept off a public profile: `UserScalar.spottings`
drops it, and `spottingsCount`, `favouriteVehicles`, `spottingTrends` and `withMostEntries`
leave it out of their figures, for everyone except the profile's owner and admins (decision
F043). They share one per-viewer filter, `_events_shown_to_viewer`
(`common/schema/scalars.py`), built on `spotting.schema.resolvers.viewer_is_owner_or_admin`.
The owner's own `user { … }` is unchanged. Tests: `AnonymousSpottingsOnProfileTests`.

**Photos.** A photo attached to an anonymous spotting (an `EventMedia` row) stays visible
everywhere, but its `uploader` (the reporter: the upload task enforces `uploader == reporter`)
resolves to `null` for everyone except that user and admins (decision F043). Both GraphQL types
over `Media` use the same gate, `common.schema.scalars.uploader_field()` (a fail-silent
`PermissionExtension` around `CanSeeUploader`), so `events { medias }`, `medias`, `media(id)`
and the incident photo edges agree; `uploader` is nullable on `MediaScalar` and `MediaType`.
`spotting.schema.resolvers.viewer_can_see_uploader` reads `anonymous_uploader_from_media_loader`
(media id to uploader id for media of an anonymous event: one query per request) and then
`viewer_is_owner_or_admin`, so a request without a hidden photo makes no Firebase call.
Two side channels are closed with it: `UserScalar.mediaCount` leaves those photos out for other
viewers, and `MediaOrder` has no `uploader` (sorting by it would group a hidden photo between
the same user's visible ones). Tests: `AnonymousPhotoUploaderTests`.

**Empty views.** `withMostEntries` is `null` (it is nullable) when the viewer can see no events,
so a profile whose spottings are all anonymous loads for a stranger; `spottingTrends(freeRange)`
falls back to its default start for an empty range.

**Known gaps:** none. The admin claim is still a live, uncached Firebase call per viewer per
request wherever `viewer_is_owner_or_admin` needs it (see `MISTAKES.md`).

## Notes

- Privacy is field-level, in the resolver; the per-user DataLoader
  (`spottings_from_user_loader`) is preserved. The caller comes from `info.context.user`.
- Tests in `common/tests.py`: `UserPrivacyTests` (default private; owner / public /
  private access), `SpottingDataPublicMigrationTests`, `TestUserInput` and
  `TestUpdateUserMutation` (omitted / true / false; null is refused).

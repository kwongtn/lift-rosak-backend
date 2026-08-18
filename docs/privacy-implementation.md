# Privacy Implementation — Public Profiles

## Database Schema

### User Model (`common.models.User`)

- **Field**: `spotting_data_public` (BooleanField)
- **Default**: `False` (strictly opt-in)
- **Migration**: `0019_user_spotting_data_public_userjejaktransaction`
- **Purpose**: Controls visibility of historical spotting data on public profiles

## GraphQL Schema

### Queries

#### `publicUser(id: ID!): UserScalar`

- **Purpose**: Fetch any user's public profile by ID
- **Authentication**: None required (public query)
- **Returns**: `UserScalar` or `null` if user not found
- **Privacy**: Field-level enforcement in `UserScalar.spottings` resolver

### Types

#### `UserScalar` (common.schema.scalars)

- **New Field**: `spotting_data_public: Boolean!`
- **Privacy Logic**: `spottings` field returns `Optional[List[EventScalar]]`
  - Owner (authenticated user viewing own profile): always returns full list
  - Non-owner + `spotting_data_public=True`: returns full list
  - Non-owner + `spotting_data_public=False`: returns `null`

### Mutations

#### `updateUser(input: UserInput!): UserScalar`

- **New Input Field**: `spotting_data_public: Optional[bool]` (default: UNSET)
- **Behavior**: Only updates when explicitly provided (not UNSET)
- **Permission**: `IsLoggedIn` (can only update own profile)

## Privacy Contract

### Always Public (Unauthenticated Access Allowed)

- Nickname
- Total spottings count (`spottingsCount`)
- Media uploaded count (`mediaCount`)
- Activity heatmap data (`spottingTrends`)
- Best month/day aggregates (`withMostEntries*`)
- Favorite vehicles (`favouriteVehicles`)

### Opt-In Only (Requires `spotting_data_public=true`)

- Historical spottings list with full details (`spottings`)
  - Includes: spotting date, notes, vehicle details, media count, status

### Never Exposed

- Email address
- Firebase UID (admin-only via `firebase_id` field with `permission_classes=[IsAdmin]`)
- Internal IDs beyond public identifiers

## Testing

See `common.tests.UserPrivacyTests` for comprehensive test coverage:

- Default privacy (new users private by default)
- Owner access (always sees own data)
- Public access (non-owner sees data when public)
- Private access (non-owner gets null when private)
- Migration verification

## Security Considerations

- Privacy is enforced at the resolver level (field-level permissions)
- `null` vs `[]` distinction: `null` = private, `[]` = no data exists
- Authentication context available via `info.context.user`
- DataLoader pattern preserved for performance

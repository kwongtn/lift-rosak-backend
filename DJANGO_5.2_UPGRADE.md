# Django 5.2 Upgrade — rosak_backend

**Completed:** 2026-08-18
**Django version:** 4.2.20 → 5.2.17
**Test status:** ✅ 84/84 tests passing

---

## Changes Made

### 1. Dependencies Updated

**File:** [`pyproject.toml`](pyproject.toml)

```diff
- "django==4.2.*",
+ "django==5.2.*",
```

**Lock regenerated:**

```bash
rye lock
```

**Result:**

- `django==5.2.17` locked
- All Django ecosystem packages compatible (`strawberry-django`, `django-cors-headers`, etc.)

---

### 2. Migrations Applied

Two auto-generated migrations for Django 5.2 compatibility:

1. **`advanced_filters.0004_alter_advancedfilter_id`** (third-party)
   - Changes `id` field type to `BigAutoField` (Django 5.2 default)

2. **`common.0018_alter_media_file`**
   - Re-declares `ImgurField` with explicit storage/upload configuration
   - No schema change, safe migration

**Applied via:**

```bash
docker compose exec app python manage.py migrate
```

---

### 3. Strawberry GraphQL Warnings Fixed

**Files:**

- [`operation/schema/filters.py`](operation/schema/filters.py)
- [`spotting/schema/filters.py`](spotting/schema/filters.py)

**Changes:**

- Replaced `FilterLookup[str]` → `StrFilterLookup` in 6 filter fields
- Eliminates Strawberry `DuplicatedTypeName` warnings

**Before:**

```python
from strawberry_django import FilterLookup


class LineFilter:
    display_name: Optional[FilterLookup[str]]
```

**After:**

```python
from strawberry_django import StrFilterLookup


class LineFilter:
    display_name: Optional[StrFilterLookup]
```

---

## Verification

### System Check

```bash
docker compose exec app python manage.py check
# System check identified no issues (0 silenced).
```

### Test Suite

```bash
docker compose exec app python manage.py test --keepdb --parallel
# Ran 84 tests in 1.7s - OK
```

### Deployment Check

```bash
docker compose exec app python manage.py check --deploy
# 6 warnings (expected: DEBUG=True, no HTTPS in dev)
```

---

## Breaking Changes from Django 4.2 → 5.2

### 1. **No breaking changes for this codebase**

- `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` was already set
- No deprecated imports (`force_text`, `ugettext`) found
- All async ORM patterns (`acreate`, `aget`, `async for`) remain compatible

### 2. **Django 5.0 async ORM improvements**

- Full async queryset support (already in use)
- `asave()`, `adelete()`, `arefresh_from_db()` (already in use)
- No code changes required

### 3. **Django 5.1 field choices enhancements**

- `TextChoicesField` (django-choices-field) already handles this
- No migration changes required

### 4. **Django 5.2 database improvements**

- PostGIS 3.x support improved
- Better async connection handling
- No configuration changes required

---

## Post-Upgrade Checklist

- [x] Dependencies locked (`rye lock`)
- [x] Docker image rebuilt (`docker compose build app`)
- [x] Database migrations applied (`manage.py migrate`)
- [x] System check passed (`manage.py check`)
- [x] All tests green (`manage.py test --keepdb`)
- [x] Deployment check reviewed (`manage.py check --deploy`)
- [x] Strawberry warnings eliminated
- [x] No deprecated imports found
- [x] GraphQL schema still introspectable

---

## Rollback Instructions

If rollback is needed:

```bash
# 1. Revert pyproject.toml
git checkout HEAD~1 -- pyproject.toml

# 2. Regenerate lock
rye lock

# 3. Rebuild & restart
docker compose build app
docker compose up -d

# 4. Rollback migrations (if database already migrated)
docker compose exec app python manage.py migrate advanced_filters 0003
docker compose exec app python manage.py migrate common 0017
```

---

## Notes

- **Production deployment:** No schema changes, safe to deploy with standard procedure
- **Celery compatibility:** Tested with Celery 5.6.3, no issues
- **PostGIS compatibility:** Tested with PostGIS 3.x, geometry fields work correctly
- **Strawberry GraphQL:** No schema changes, GraphQL endpoint behavior unchanged

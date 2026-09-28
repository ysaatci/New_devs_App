# Revenue Dashboard Fixes

Run `bash scripts/repro.sh` with the docker-compose stack running to reproduce the results below.
Output from before and after each fix is in `docs/evidence/`.

## 1. Revenue was not read from the database (`ac23b31`)

**Problem:** Sunset's totals did not match the database.

**Cause:** `DatabasePool` used settings that do not exist (`supabase_db_*`), a pool class that does not
work with async, and `get_session` was used incorrectly. The `greenlet` package was also missing.
The error was caught and the code returned hard-coded numbers for each property.

**Fix:** Use `DATABASE_URL`, reuse one shared pool, add `sqlalchemy[asyncio]`, and return 503 instead of
hard-coded numbers.

## 2. Cache key did not include the tenant (`51ce5bb`)

**Problem:** Ocean saw another company's revenue after a refresh.

**Cause:** The cache key was `revenue:{property_id}`. `prop-001` exists for both Sunset and Ocean, so
the first client to load it filled the cache and the other client got the same data for 5 minutes.
This was hidden by bug 1 until the database connection worked.

**Fix:** The key is now `revenue:{tenant_id}:{property_id}:{period}`.

## 3. Months were calculated in UTC (`bd6b5dc`)

**Problem:** Sunset's March total was wrong.

**Cause:** Booking `res-tz-1` starts at `2024-02-29 23:30 UTC`, which is `2024-03-01 00:30` in Paris.
Using UTC, it was counted in February. March showed 1000.00 from 3 bookings instead of 2250.00 from 4.
The API also had no way to request a single month.

**Fix:** The query converts `check_in_date` to the property's time zone before comparing. Added
`year` and `month` parameters to `/dashboard/summary` and a month filter to the dashboard.

## 4. Rounding errors (`f0151af`)

**Problem:** Some totals were off by a few cents.

**Cause:** Amounts are stored with three decimals. The API returned the total without rounding and
the frontend rounded it with floating point math (`Math.round(x * 100) / 100`), which rounds some
values wrong (for example 1.005 becomes 1.00). Currency was hard-coded to USD.

**Fix:** The database adds the exact amounts, the backend rounds the total once with `Decimal`
(half up), and the frontend shows it as it is. Currency comes from the data.

## 5. Tenant checks (`682f353`)

**Problem:** Found during the investigation.

**Cause:** The dashboard listed every company's properties. Unknown users were given `tenant-a`.
A missing tenant fell back to `default_tenant`. Requesting another tenant's property returned 0
instead of an error.

**Fix:** Added `/dashboard/properties` for the logged-in tenant. Unknown users get no tenant.
Missing tenant returns 403. Another tenant's property returns 404.

## Results

| Check | Before | After |
|-------|--------|-------|
| Ocean `prop-001` after Sunset loaded it | 2250.00 (Sunset's) | 0.00, 0 bookings |
| Ocean requests Sunset's `prop-002` | 4975.50 | 404 |
| Sunset `prop-001`, March 2024 | 1000.00, 3 bookings | 2250.00, 4 bookings |
| Sunset `prop-001`, February 2024 | - | 0.00, 0 bookings |
| Rounding 1.005 / 2.675 | 1.00 / 2.67 | 1.01 / 2.68 |

## Not fixed

- `backend/app/api/v1/departments.py` does not filter by tenant when the tenant is missing.
- Row-level security is enabled on the tables but there are no policies.
- `frontend/node_modules` and `frontend/dist` are committed to the repo.

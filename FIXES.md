# Revenue Dashboard – Investigation & Fixes

Reproduce any of this against the running stack with `bash scripts/repro.sh`.
Captured output before/after each fix is in [`docs/evidence/`](docs/evidence/).

| # | Reported symptom | Root cause | Fix (commit) |
|---|------------------|------------|--------------|
| 1 | Totals don't match client records | Revenue was **never read from Postgres**. `DatabasePool` read non-existent `settings.supabase_db_*` fields, forced `QueuePool` on an async engine, used a coroutine as `async with`, and `greenlet` was missing. The error was swallowed and every request returned **hard-coded mock figures** that ignored the tenant. | Build URL from `settings.database_url`, reuse the shared pool, add `sqlalchemy[asyncio]`, return 503 instead of fake data. (`ac23b31`) |
| 2 | Client B sees another company's revenue on refresh | Redis key was `revenue:{property_id}`. Property IDs are only unique **per tenant** – `prop-001` is Sunset's *Beach House Alpha* **and** Ocean's *Mountain Lodge Beta*. First tenant to load fills the cache; the other tenant is served it for 5 min. (Masked by bug 1 until the DB was reachable.) | Key is `revenue:{tenant_id}:{property_id}:{period}`. (`51ce5bb`) |
| 3 | Client A's **March** totals differ | Month boundaries were naive UTC midnights. `res-tz-1` checks in `2024-02-29 23:30 UTC` = **`2024-03-01 00:30` Europe/Paris**, so it fell into February. UTC March: 1000.00 / 3 bookings; correct local March: **2250.00 / 4**. There was also no way to request a month at all. | Compare `check_in_date AT TIME ZONE properties.timezone` against the local month; `year`/`month` params on `/dashboard/summary`; month picker in the UI. (`bd6b5dc`) |
| 4 | Totals "off by a few cents" | Amounts are `NUMERIC(10,3)` (e.g. 333.333 + 333.333 + 333.334). Totals left the API unrounded and were re-rounded in the browser with `Math.round(x*100)/100` – binary floats misround half-cents (`1.005 → 1.00`), and any per-row rounding gives 999.99 instead of 1000.00. Currency was hard-coded to USD. | Sum exactly in SQL, round **once** to cents with `Decimal` `ROUND_HALF_UP`, display as-is; currency from data, refuse mixed-currency sums. (`f0151af`) |
| 5 | (Privacy hardening found during investigation) | Frontend hard-coded **all tenants'** properties; unknown users defaulted to `tenant-a`; missing tenant fell back to `"default_tenant"`; foreign property returned an empty 0 instead of an error. | `/dashboard/properties` per tenant, resolver returns `None`, 403 without tenant, 404 for another tenant's property. (`682f353`) |

## Verified results (after all fixes)

| Check | Before | After |
|-------|--------|-------|
| Ocean `prop-001` after Sunset loaded it | Sunset's 2250.00 / 4 | **0.00 / 0** (Mountain Lodge Beta) |
| Ocean requests Sunset's `prop-002` | 4975.50 (Sunset's data) | **404** |
| Sunset `prop-001`, March 2024 | 1000.00 / 3 | **2250.00 / 4** |
| Sunset `prop-001`, February 2024 | – | **0.00 / 0** |
| Rounding of 1.005 / 2.675 | 1.00 / 2.67 | **1.01 / 2.68** |

## Out of scope / follow-ups
- `backend/app/api/v1/departments.py` lists all departments when `user.tenant_id` is empty (same fail-open pattern; inactive in this setup since it uses Supabase).
- `frontend/node_modules` and `frontend/dist` are committed to the repo.
- Postgres RLS is enabled but no policies exist; isolation relies entirely on application queries.

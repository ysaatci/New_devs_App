#!/usr/bin/env bash
# Reproduces the reported revenue dashboard issues against the running
# docker-compose stack. Run from the repo root:  bash scripts/repro.sh
set -u

API=${API:-http://localhost:8000}

token() {
  curl -s -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" |
    python -c "import sys, json; print(json.load(sys.stdin)['access_token'])"
}

summary() { # token property_id [extra query]
  curl -s "$API/api/v1/dashboard/summary?property_id=$2${3:-}" -H "Authorization: Bearer $1"
  echo
}

redis() { docker compose exec -T redis redis-cli "$@" 2>/dev/null; }
psql_q() { docker compose exec -T db psql -U postgres -d propertyflow -c "$1" 2>/dev/null; }

A=$(token sunset@propertyflow.com client_a_2024)
B=$(token ocean@propertyflow.com client_b_2024)

echo "=== 0. Ground truth in Postgres"
psql_q "SELECT tenant_id, property_id, COUNT(*) AS bookings, SUM(total_amount) AS total
        FROM reservations GROUP BY 1, 2 ORDER BY 1, 2;"

echo "=== 1. Cross-tenant cache: prop-001 exists in BOTH tenants"
redis FLUSHALL >/dev/null
echo -n "Sunset prop-001 (first load): "; summary "$A" prop-001
echo -n "Ocean  prop-001 (refresh):    "; summary "$B" prop-001
echo "Redis keys:"; redis KEYS 'revenue:*'

echo "=== 2. Ocean asking for a Sunset-only property"
echo -n "Ocean  prop-002: "; summary "$B" prop-002
echo "Property list each tenant is offered:"
echo -n "Sunset: "; curl -s "$API/api/v1/dashboard/properties" -H "Authorization: Bearer $A"; echo
echo -n "Ocean:  "; curl -s "$API/api/v1/dashboard/properties" -H "Authorization: Bearer $B"; echo

echo "=== 3. March 2024 for Beach House Alpha (Europe/Paris)"
psql_q "SELECT r.id, r.check_in_date AT TIME ZONE 'UTC' AS check_in_utc,
               r.check_in_date AT TIME ZONE p.timezone AS check_in_local, p.timezone
        FROM reservations r
        JOIN properties p ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.id = 'res-tz-1';"
psql_q "SELECT 'UTC month boundaries' AS method, COUNT(*), SUM(r.total_amount)
        FROM reservations r
        WHERE r.property_id = 'prop-001' AND r.tenant_id = 'tenant-a'
          AND r.check_in_date >= '2024-03-01 00:00+00' AND r.check_in_date < '2024-04-01 00:00+00'
        UNION ALL
        SELECT 'property-local boundaries', COUNT(*), SUM(r.total_amount)
        FROM reservations r
        JOIN properties p ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = 'prop-001' AND r.tenant_id = 'tenant-a'
          AND (r.check_in_date AT TIME ZONE p.timezone) >= '2024-03-01'
          AND (r.check_in_date AT TIME ZONE p.timezone) < '2024-04-01';"
echo -n "Sunset prop-001 March 2024:    "; summary "$A" prop-001 "&year=2024&month=3"
echo -n "Sunset prop-001 February 2024: "; summary "$A" prop-001 "&year=2024&month=2"

echo "=== 4. Precision: sub-cent amounts (NUMERIC(10,3)) and rounding"
psql_q "SELECT id, total_amount FROM reservations WHERE id LIKE 'res-dec-%' ORDER BY id;"
python - <<'PY'
from decimal import Decimal, ROUND_HALF_UP
rows = ["333.333", "333.333", "333.334"]
print("round each row to cents :", sum(Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP) for x in rows))
print("sum exactly, round once :", sum(Decimal(x) for x in rows).quantize(Decimal("0.01"), ROUND_HALF_UP))
print("float round(2.675, 2)   :", round(2.675, 2), "(half-up gives 2.68)")
PY
node -e "console.log('JS Math.round(1.005*100)/100 :', Math.round(1.005 * 100) / 100, '(half-up gives 1.01)')" 2>/dev/null
docker compose exec -T backend python -c "
from decimal import Decimal
from app.services.reservations import to_cents
for v in ['1000.000', '2.675', '1.005', '666.666']: print('to_cents(' + v + ') =', to_cents(Decimal(v)))" 2>/dev/null
echo "API totals:"
for p in prop-001 prop-002 prop-003; do echo -n "Sunset $p: "; summary "$A" $p; done
for p in prop-004 prop-005; do echo -n "Ocean  $p: "; summary "$B" $p; done

echo "=== Backend errors (last 3)"
docker compose logs backend 2>/dev/null | grep -iE "database error|pool init|Traceback" | tail -3

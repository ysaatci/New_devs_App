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

echo "=== 3. March 2024 for Beach House Alpha (Europe/Paris)"
psql_q "SELECT r.id, r.check_in_date AT TIME ZONE 'UTC' AS check_in_utc,
               r.check_in_date AT TIME ZONE p.timezone AS check_in_local, p.timezone
        FROM reservations r
        JOIN properties p ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.id = 'res-tz-1';"
echo -n "Sunset prop-001 March 2024:    "; summary "$A" prop-001 "&year=2024&month=3"
echo -n "Sunset prop-001 February 2024: "; summary "$A" prop-001 "&year=2024&month=2"

echo "=== 4. Precision: raw totals the API hands to the frontend"
for p in prop-001 prop-002 prop-003; do echo -n "Sunset $p: "; summary "$A" $p; done
for p in prop-004 prop-005; do echo -n "Ocean  $p: "; summary "$B" $p; done

echo "=== Backend errors (last 3)"
docker compose logs backend 2>/dev/null | grep -iE "database error|pool init|Traceback" | tail -3

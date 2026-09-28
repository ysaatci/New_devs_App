from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional

CENTS = Decimal("0.01")


def to_cents(amount: Decimal) -> Decimal:
    """
    Rounds a money amount to cents exactly once, half-up. Amounts are stored with
    sub-cent precision (NUMERIC(10,3)), so they must be summed at full precision
    first; rounding per reservation or in binary floats drifts by cents
    (e.g. 333.333 + 333.333 + 333.334 -> 999.99 when rounded per row).
    """
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class PropertyNotFound(LookupError):
    """The property does not exist for the requesting tenant."""


async def get_tenant_properties(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Lists the properties that belong to a tenant.
    """
    from app.core.database_pool import db_pool
    from sqlalchemy import text

    if not db_pool.session_factory:
        await db_pool.initialize()
    if not db_pool.session_factory:
        raise Exception("Database pool not available")

    async with db_pool.get_session() as session:
        result = await session.execute(
            text("""
                SELECT id, name, timezone
                FROM properties
                WHERE tenant_id = :tenant_id
                ORDER BY id
            """),
            {"tenant_id": tenant_id},
        )
        return [{"id": row.id, "name": row.name, "timezone": row.timezone} for row in result]


async def _aggregate_revenue(
    property_id: str,
    tenant_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Sums reservation revenue for one tenant's property, optionally limited to
    check-ins in [start_date, end_date). The bounds are naive datetimes in the
    property's local time zone: check_in_date is converted with
    `AT TIME ZONE properties.timezone` before comparing, so a booking at
    2024-02-29 23:30 UTC for a Paris property counts towards March.
    """
    try:
        # Reuse the shared database pool; initialize it on first use
        from app.core.database_pool import db_pool

        if not db_pool.session_factory:
            await db_pool.initialize()

        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text

                period_filter = ""
                params = {"property_id": property_id, "tenant_id": tenant_id}
                if start_date is not None and end_date is not None:
                    period_filter = """
                        AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
                        AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date
                    """
                    params.update(start_date=start_date, end_date=end_date)

                # Start from the tenant's own property so that a property belonging to
                # another tenant yields no row at all (404) rather than an empty total.
                query = text(f"""
                    SELECT
                        SUM(r.total_amount) as total_revenue,
                        COUNT(r.id) as reservation_count,
                        MIN(r.currency) as currency,
                        COUNT(DISTINCT r.currency) as currency_count
                    FROM properties p
                    LEFT JOIN reservations r
                      ON r.property_id = p.id AND r.tenant_id = p.tenant_id
                      {period_filter}
                    WHERE p.id = :property_id AND p.tenant_id = :tenant_id
                    GROUP BY p.id
                """)

                result = await session.execute(query, params)
                row = result.fetchone()

                if row is None:
                    raise PropertyNotFound(property_id)

                if row.reservation_count:
                    if row.currency_count > 1:
                        # Summing amounts in different currencies would produce a meaningless total
                        raise ValueError(f"Mixed currencies for property {property_id}")
                    # SUM over NUMERIC is exact; round to cents only once, on the final total
                    total_revenue = to_cents(Decimal(str(row.total_revenue)))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": row.currency or "USD",
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property (in this period)
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")

    except PropertyNotFound:
        raise
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        # Never serve placeholder figures for financial data; let the caller report the outage
        raise


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Dict[str, Any]:
    """
    Calculates revenue for a calendar month in the property's local time zone.
    """
    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)

    return await _aggregate_revenue(property_id, tenant_id, start_date, end_date)


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates all-time revenue from database.
    """
    return await _aggregate_revenue(property_id, tenant_id)

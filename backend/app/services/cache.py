import json
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches revenue summary (all-time, or for one month when year/month are given),
    utilizing caching to improve performance.
    """
    period = f"{year:04d}-{month:02d}" if year and month else "all"
    # Property IDs are only unique per tenant (e.g. prop-001 exists in several tenants),
    # so the tenant must be part of the key or one client's figures are served to another.
    cache_key = f"revenue:{tenant_id}:{property_id}:{period}"

    # Try to get from cache
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue, calculate_monthly_revenue

    # Calculate revenue
    if period == "all":
        result = await calculate_total_revenue(property_id, tenant_id)
    else:
        result = await calculate_monthly_revenue(property_id, tenant_id, month, year)

    # Cache the result for 5 minutes
    await redis_client.setex(cache_key, 300, json.dumps(result))

    return result

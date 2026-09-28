from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional
from app.services.cache import get_revenue_summary
from app.services.reservations import PropertyNotFound, get_tenant_properties
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()


def _require_tenant(current_user) -> str:
    """Fail closed: without a resolved tenant we cannot scope any data."""
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant associated with this account")
    return tenant_id


@router.get("/dashboard/properties")
async def get_dashboard_properties(
    current_user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    tenant_id = _require_tenant(current_user)
    try:
        return await get_tenant_properties(tenant_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Property data is temporarily unavailable")


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:

    if (year is None) != (month is None):
        raise HTTPException(status_code=422, detail="year and month must be provided together")

    tenant_id = _require_tenant(current_user)

    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, year, month)
    except PropertyNotFound:
        raise HTTPException(status_code=404, detail="Property not found")
    except Exception:
        raise HTTPException(status_code=503, detail="Revenue data is temporarily unavailable")

    # 'total' is already rounded to cents exactly once (Decimal, half-up) in the
    # service layer; clients must display it as-is rather than re-rounding floats.
    total_revenue_float = float(revenue_data['total'])

    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": total_revenue_float,
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count']
    }

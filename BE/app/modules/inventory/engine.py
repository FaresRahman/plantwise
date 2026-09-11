"""Run-out projection + low-stock compute for Inventory. Deliberately simple,
explainable linear projection from trailing consumption — NOT ML, per PRD.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import Item, StockMovement


def _trailing_daily_rate(rows: list[StockMovement], field: str) -> float:
    """Average daily rate of `field` (qty_out or qty_in) over the rows passed
    in, divided by the number of distinct days that actually saw movement
    (not by the full window length) — same convention as the direct
    consumption calc below.
    """
    total = sum(getattr(r, field) or 0 for r in rows)
    distinct_days = {r.timestamp.date() for r in rows if (getattr(r, field) or 0) > 0}
    divisor = max(1, len(distinct_days))
    return (total / divisor) if total > 0 else 0.0


async def get_bom_dependents(db: AsyncSession, tenant_id: int) -> list[Item]:
    """Every item in the tenant with a non-empty bill_of_materials — fetch
    this ONCE per batch (get_low_stock_items, the /items list endpoint) and
    pass it into compute_item_projection/_bom_implied_consumption rather
    than letting each item's projection re-run this same tenant-wide query;
    otherwise projecting N items costs an extra O(N) "all items with a BOM"
    query on top of the per-dependent stock-movement lookups.
    """
    return list(
        (
            await db.scalars(
                select(Item).where(Item.tenant_id == tenant_id, Item.bill_of_materials.isnot(None))
            )
        ).all()
    )


async def _bom_implied_consumption(
    db: AsyncSession, tenant_id: int, component_sku: str, dependents: list[Item] | None = None
) -> float:
    """How fast this component is *implied* to be consumed by other items'
    production, derived from their own bill_of_materials + trailing output
    rate — e.g. Widget-A's BOM says "2x RM-STEEL-1 per unit"; if Widget-A is
    being produced at N units/day (its own qty_in rate), that implies
    2N units/day of steel consumption even if steel's own qty_out was never
    logged directly. Previously bill_of_materials was captured and editable
    but never read anywhere, so it had no effect on run-out projections —
    this is what BRD §6.4's own cross-module example ("do we have material
    for tomorrow?") depends on.
    """
    if dependents is None:
        dependents = await get_bom_dependents(db, tenant_id)

    window_start = datetime.utcnow() - timedelta(days=7)
    implied = 0.0
    for dependent in dependents:
        bom = dependent.bill_of_materials or {}
        qty_per_unit = bom.get(component_sku)
        if not qty_per_unit:
            continue
        rows = (
            await db.scalars(
                select(StockMovement).where(
                    StockMovement.tenant_id == tenant_id,
                    StockMovement.item_id == dependent.id,
                    StockMovement.timestamp >= window_start,
                )
            )
        ).all()
        production_rate = _trailing_daily_rate(rows, "qty_in")
        implied += production_rate * qty_per_unit
    return implied


async def compute_item_projection(
    db: AsyncSession, tenant_id: int, item: Item, dependents: list[Item] | None = None
) -> dict:
    # Most recent movement row -> current_qty (0 if the item has no movements yet)
    latest = await db.scalar(
        select(StockMovement)
        .where(StockMovement.tenant_id == tenant_id, StockMovement.item_id == item.id)
        .order_by(StockMovement.timestamp.desc())
        .limit(1)
    )
    has_data = latest is not None
    current_qty = latest.current_qty if latest else 0.0

    # Trailing-7-day consumption rate. `timestamp` is stored naive (see
    # models.py) so we compare against a naive UTC "now" to avoid aware/naive
    # subtraction errors.
    window_start = datetime.utcnow() - timedelta(days=7)
    rows = (
        await db.scalars(
            select(StockMovement).where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.item_id == item.id,
                StockMovement.timestamp >= window_start,
            )
        )
    ).all()

    direct_consumption = _trailing_daily_rate(rows, "qty_out")
    # Take the max rather than summing: a directly-logged qty_out and a
    # BOM-implied rate are two different ways of estimating the same
    # physical depletion, not two additive sources of it — summing them
    # would double-count a plant that already logs component consumption
    # directly. The BOM-implied side only takes over when it's the larger
    # (better) signal, e.g. a raw material whose own movements are logged
    # sparsely but whose downstream finished good's output is tracked well.
    bom_implied = await _bom_implied_consumption(db, tenant_id, item.sku, dependents=dependents)
    daily_consumption = max(direct_consumption, bom_implied)

    days_to_runout = (current_qty / daily_consumption) if daily_consumption > 0 else None
    runout_date = (date.today() + timedelta(days=days_to_runout)) if days_to_runout is not None else None

    # BRD §5.2: "missing expected data shown as a gap, not a zero" — an item
    # with no stock-movement rows yet has an *unknown* stock level, not a
    # literal 0 on hand; without this guard, a freshly-configured item (with
    # its default reorder_point of 0) would satisfy `0 <= 0` and be flagged
    # "low stock" before anyone ever uploaded a movement for it.
    is_low = has_data and (
        current_qty <= item.reorder_point
        or (days_to_runout is not None and days_to_runout <= item.supplier_lead_time_days)
    )

    return {
        "current_qty": round(current_qty, 2) if has_data else None,
        "daily_consumption": round(daily_consumption, 2),
        "days_to_runout": round(days_to_runout, 1) if days_to_runout is not None else None,
        "runout_date": runout_date.isoformat() if runout_date else None,
        "is_low": is_low,
        "has_data": has_data,
    }


async def get_low_stock_items(db: AsyncSession, tenant_id: int) -> list[dict]:
    items = (await db.scalars(select(Item).where(Item.tenant_id == tenant_id))).all()
    dependents = await get_bom_dependents(db, tenant_id)
    low: list[dict] = []
    for item in items:
        projection = await compute_item_projection(db, tenant_id, item, dependents=dependents)
        if projection["is_low"]:
            low.append({"id": item.id, "sku": item.sku, "name": item.name, **projection})
    return low


async def get_items_moved_in_window(db: AsyncSession, tenant_id: int, start: datetime, end: datetime) -> set[int]:
    """Item ids with at least one stock movement inside [start, end) — used to
    scope "items at risk this shift" to items whose stock actually moved
    during that shift, not just every item that happens to be low right now.
    """
    rows = await db.scalars(
        select(StockMovement.item_id)
        .where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.timestamp >= start,
            StockMovement.timestamp < end,
        )
        .distinct()
    )
    return set(rows.all())

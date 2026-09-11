from datetime import datetime, timedelta, timezone
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ChatToolSpec, ModuleSummary, ShiftContribution, register_tool
from app.core.freshness import get_freshness
from app.core.ingestion import ColumnSpec, CSVSpec
from app.core.models_shared import ModuleFreshness
from app.modules.inventory.engine import (
    compute_item_projection,
    get_bom_dependents,
    get_items_moved_in_window,
    get_low_stock_items,
)
from app.modules.inventory.models import Item, StockMovement


# ---------------------------------------------------------------------------
# Item config CRUD helpers
# ---------------------------------------------------------------------------


async def list_items(db: AsyncSession, tenant_id: int) -> list[Item]:
    return list((await db.scalars(select(Item).where(Item.tenant_id == tenant_id))).all())


async def get_item(db: AsyncSession, tenant_id: int, item_id: int) -> Item | None:
    return await db.scalar(select(Item).where(Item.tenant_id == tenant_id, Item.id == item_id))


async def get_item_by_sku(db: AsyncSession, tenant_id: int, sku: str) -> Item | None:
    return await db.scalar(select(Item).where(Item.tenant_id == tenant_id, Item.sku == sku))


async def item_projection_payload(
    db: AsyncSession, tenant_id: int, item: Item, dependents: list[Item] | None = None
) -> dict:
    projection = await compute_item_projection(db, tenant_id, item, dependents=dependents)
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "sku": item.sku,
        "name": item.name,
        "item_type": item.item_type,
        "unit_of_measure": item.unit_of_measure,
        "reorder_point": item.reorder_point,
        "supplier_lead_time_days": item.supplier_lead_time_days,
        "bill_of_materials": item.bill_of_materials,
        "created_at": item.created_at,
        "projection": projection,
    }


# ---------------------------------------------------------------------------
# Item config CSV
# ---------------------------------------------------------------------------


async def _check_item_exists_for_upsert(db: AsyncSession, tenant_id: int, parsed: dict) -> str | None:
    """Non-blocking warning: tells user this SKU already exists and will be updated."""
    sku = parsed.get("sku")
    if not sku:
        return None
    existing = await db.scalar(select(Item).where(Item.tenant_id == tenant_id, Item.sku == sku))
    if existing is not None:
        return f"sku '{sku}' already exists — will be updated on commit"
    return None


ITEM_CSV_SPEC = CSVSpec(
    module="inventory",
    columns=[
        ColumnSpec(name="sku", dtype="str"),
        ColumnSpec(name="name", dtype="str"),
        ColumnSpec(name="item_type", dtype="enum", required=False, enum_values=["raw", "wip", "finished"]),
        ColumnSpec(name="unit_of_measure", dtype="str", required=False),
        ColumnSpec(name="reorder_point", dtype="float", required=False),
        ColumnSpec(name="supplier_lead_time_days", dtype="int", required=False),
    ],
    row_warnings=[_check_item_exists_for_upsert],
)


async def commit_items_config(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Upsert items from CSV: create new, update existing by sku."""
    created = 0
    updated = 0
    for row in valid_rows:
        existing = await db.scalar(select(Item).where(Item.tenant_id == tenant_id, Item.sku == row["sku"]))
        if existing is not None:
            existing.name = row["name"]
            existing.item_type = row.get("item_type") or "raw"
            existing.unit_of_measure = row.get("unit_of_measure") or "unit"
            existing.reorder_point = row.get("reorder_point") or 0
            existing.supplier_lead_time_days = row.get("supplier_lead_time_days") or 0
            updated += 1
        else:
            db.add(Item(
                tenant_id=tenant_id,
                sku=row["sku"],
                name=row["name"],
                item_type=row.get("item_type") or "raw",
                unit_of_measure=row.get("unit_of_measure") or "unit",
                reorder_point=row.get("reorder_point") or 0,
                supplier_lead_time_days=row.get("supplier_lead_time_days") or 0,
            ))
            created += 1
    await db.commit()
    return created, updated


# ---------------------------------------------------------------------------
# CSV ingestion — stock movements
# ---------------------------------------------------------------------------


async def _sku_exists(db: AsyncSession, tenant_id: int, value: str) -> bool:
    return await get_item_by_sku(db, tenant_id, value) is not None


STOCK_MOVEMENT_CSV_SPEC = CSVSpec(
    module="inventory",
    columns=[
        ColumnSpec(name="sku", dtype="str", required=True),
        ColumnSpec(name="timestamp", dtype="datetime", required=True),
        ColumnSpec(name="current_qty", dtype="float", required=True),
        ColumnSpec(name="qty_in", dtype="float", required=False),
        ColumnSpec(name="qty_out", dtype="float", required=False),
        ColumnSpec(name="movement_reason", dtype="str", required=False),
    ],
    fk_checks={"sku": _sku_exists},
)

STOCK_MOVEMENT_CSV_HEADER = "sku,timestamp,current_qty,qty_in,qty_out,movement_reason"


async def commit_stock_movements(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, set[int]]:
    """Returns (rows committed, item ids actually touched by this upload) —
    the caller uses the touched-id set to scope low-stock re-alerting to
    items this upload actually affected, the same way the quick-log endpoint
    already does, instead of re-checking every currently-low item tenant-wide
    on every upload.
    """
    committed = 0
    touched: set[int] = set()
    for row in valid_rows:
        item = await get_item_by_sku(db, tenant_id, row["sku"])
        if item is None:
            # Shouldn't happen if the row already passed the fk_check, but
            # guard against a race (item deleted between validate and commit).
            continue
        db.add(
            StockMovement(
                tenant_id=tenant_id,
                item_id=item.id,
                timestamp=row["timestamp"],
                current_qty=row.get("current_qty") or 0,
                qty_in=row.get("qty_in") or 0,
                qty_out=row.get("qty_out") or 0,
                movement_reason=row.get("movement_reason"),
            )
        )
        committed += 1
        touched.add(item.id)
    await db.commit()
    return committed, touched


async def resync_low_stock_alerts(db: AsyncSession, tenant_id: int, item_ids: set[int]) -> None:
    """Re-evaluate low-stock status for exactly the items a stock-movement
    write touched, and trigger or clear the alert accordingly. Replaces two
    separate ad-hoc loops (CSV commit, quick-log) that only ever triggered —
    an item that's no longer low (restocked) never had its alert cleared, so
    a later recurrence would be silently suppressed by the stale SentAlert
    row from before.
    """
    from app.modules.notifications.service import clear_generic_alert, trigger_generic_alert

    for item_id in item_ids:
        item = await get_item(db, tenant_id, item_id)
        if item is None:
            continue
        projection = await compute_item_projection(db, tenant_id, item)
        title = f"{item.name} low stock"
        if projection["is_low"]:
            await trigger_generic_alert(
                db,
                tenant_id,
                "inventory",
                title=title,
                message=(
                    f"{item.name} ({item.sku}) at {projection['current_qty']} units"
                    + (f", projected run-out {projection['runout_date']}" if projection["runout_date"] else "")
                ),
                dashboard_link="/inventory",
            )
        else:
            await clear_generic_alert(db, tenant_id, "inventory", title)


# ---------------------------------------------------------------------------
# Consumption trend (analytics §5.7)
# ---------------------------------------------------------------------------


async def get_consumption_trend(db: AsyncSession, tenant_id: int, item_id: int, days: int = 30) -> list[dict]:
    """Daily consumption over the last N days — one data point per day with
    qty_in, qty_out, and net change. Aggregated from StockMovement rows."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        await db.scalars(
            select(StockMovement)
            .where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.item_id == item_id,
                StockMovement.timestamp >= since,
            )
            .order_by(StockMovement.timestamp.asc())
        )
    ).all()

    # Group by date
    by_date: dict[str, dict] = defaultdict(lambda: {"date": "", "qty_in": 0, "qty_out": 0})
    for r in rows:
        d = r.timestamp.strftime("%Y-%m-%d")
        by_date[d]["date"] = d
        by_date[d]["qty_in"] += r.qty_in or 0
        by_date[d]["qty_out"] += r.qty_out or 0

    return sorted(by_date.values(), key=lambda x: x["date"])


# ---------------------------------------------------------------------------
# Dashboard card + shift contribution
# ---------------------------------------------------------------------------


async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    items = await list_items(db, tenant_id)
    low_items = await get_low_stock_items(db, tenant_id)

    critical = any(i["days_to_runout"] is not None and i["days_to_runout"] <= 1 for i in low_items)
    if critical:
        status = "critical"
    elif low_items:
        status = "warning"
    else:
        status = "ok"

    headline = f"{len(low_items)} item{'s' if len(low_items) != 1 else ''} low stock" if low_items else "Stock levels healthy"

    freshness = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == "inventory")
    )
    last_updated_at = freshness.last_updated_at if freshness else None
    cadence_hours = freshness.expected_cadence_hours if freshness else None
    is_stale = False
    if freshness is not None and last_updated_at is not None:
        ts = last_updated_at if last_updated_at.tzinfo else last_updated_at.replace(tzinfo=timezone.utc)
        is_stale = (datetime.now(timezone.utc) - ts).total_seconds() > freshness.expected_cadence_hours * 3600

    return ModuleSummary(
        module="inventory",
        title="Inventory",
        status=status,
        headline=headline,
        metrics=[
            {"label": "Low stock", "value": str(len(low_items))},
            {"label": "Items", "value": str(len(items))},
        ],
        last_updated_at=last_updated_at,
        is_stale=is_stale,
        expected_cadence_hours=cadence_hours,
        alerts_count=len(low_items) if freshness is not None and freshness.last_updated_at is not None else None,
        drilldown_path="/inventory",
    )


async def get_shift_contribution(db: AsyncSession, tenant_id: int, start: datetime, end: datetime) -> ShiftContribution:
    # "Items at risk this shift" (PRD §3.3/§5.4) means low-stock items whose
    # stock actually moved during [start, end) — not every item that happens
    # to be low right now, regardless of whether this shift touched it.
    all_low_items = await get_low_stock_items(db, tenant_id)
    active_item_ids = await get_items_moved_in_window(db, tenant_id, start, end)
    low_items = [i for i in all_low_items if i["id"] in active_item_ids]

    if not low_items:
        return ShiftContribution(module="inventory", summary_text="No inventory risks this shift.", data={"items": []})

    worst = min(
        (i for i in low_items if i["runout_date"] is not None),
        key=lambda i: i["runout_date"],
        default=low_items[0],
    )
    if worst.get("runout_date"):
        summary_text = f"{worst['name']} low — projected run-out {worst['runout_date']}, reorder recommended."
    else:
        summary_text = f"{worst['name']} below reorder point, reorder recommended."

    open_items = [
        (
            f"{i['name']} ({i['sku']}): {i['current_qty']} {('units')} on hand"
            + (f", run-out ~{i['runout_date']}" if i["runout_date"] else "")
        )
        for i in low_items
    ]

    return ShiftContribution(
        module="inventory",
        summary_text=summary_text,
        data={"items": low_items},
        open_items=open_items,
    )


# ---------------------------------------------------------------------------
# Chat tool
# ---------------------------------------------------------------------------


class InventoryRunoutArgs(BaseModel):
    sku: str


async def _resolve_item(db: AsyncSession, tenant_id: int, sku_or_name: str) -> Item | None:
    """Callers (chat included) rarely type the exact SKU code, e.g. "Bottle
    Caps 28mm" instead of "PKG-CAP" — resolve against both SKU and item name
    before giving up, using the same fuzzy-match convention as shift_reports'
    schedule lookup (app.core.dimension_resolver), rather than requiring an
    exact code and silently returning "not found."
    """
    exact = await get_item_by_sku(db, tenant_id, sku_or_name)
    if exact is not None:
        return exact

    from app.core.dimension_resolver import resolve

    items = await list_items(db, tenant_id)
    by_name = {i.name: i for i in items}
    result = resolve(sku_or_name, list(by_name.keys()))
    if result.matched:
        return by_name[result.matched]
    return None


async def get_inventory_runout(db: AsyncSession, tenant_id: int, sku: str) -> dict:
    item = await _resolve_item(db, tenant_id, sku)
    if item is None:
        return {"error": f"No item found matching '{sku}'. Use inventory_list_items to see valid SKUs/names."}
    projection = await compute_item_projection(db, tenant_id, item)
    if not projection["has_data"]:
        return {
            "sku": item.sku,
            "name": item.name,
            "message": "No stock-movement data has been uploaded for this item yet.",
        }
    return {
        "sku": item.sku,
        "name": item.name,
        "current_qty": projection["current_qty"],
        "daily_consumption": projection["daily_consumption"],
        "runout_date": projection["runout_date"],
        "reorder_point": item.reorder_point,
        "supplier_lead_time_days": item.supplier_lead_time_days,
        "is_low": projection["is_low"],
        "freshness": await get_freshness(db, tenant_id, "inventory"),
    }


register_tool(
    ChatToolSpec(
        name="inventory_runout_projection",
        description=(
            "Current stock, consumption rate, and run-out projection for a given item. Accepts either "
            "the exact SKU or the item's plain-language name."
        ),
        args_schema=InventoryRunoutArgs,
        fn=get_inventory_runout,
    )
)


class ListItemsArgs(BaseModel):
    pass


async def list_items_tool(db: AsyncSession, tenant_id: int) -> dict:
    items = await list_items(db, tenant_id)
    return {
        "items": [
            {"sku": i.sku, "name": i.name, "item_type": i.item_type, "unit_of_measure": i.unit_of_measure}
            for i in items
        ]
    }


register_tool(
    ChatToolSpec(
        name="inventory_list_items",
        description="Lists every configured inventory item (SKU, name, type, unit of measure) for this tenant.",
        args_schema=ListItemsArgs,
        fn=list_items_tool,
    )
)


# ---------------------------------------------------------------------------
# Load sample data (BRD §5.1/§2.1). RM-STEEL-1 matches the BRD's own §4.3
# worked example (steel sheet, ~1,240 on hand, trending toward a near-term
# run-out) so the demo narrative lines up with the doc. WIDGET-A's BOM
# references both raw-material SKUs, per the same example.
# ---------------------------------------------------------------------------


async def load_sample_data(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    now = datetime.utcnow()

    existing = await get_item_by_sku(db, tenant_id, "RM-STEEL-1")
    if existing:
        return {"items_seeded": [], "movements_seeded": 0, "note": "already seeded"}

    steel = Item(
        tenant_id=tenant_id,
        sku="RM-STEEL-1",
        name="Steel sheet 2mm",
        item_type="raw",
        unit_of_measure="sheets",
        reorder_point=300,
        supplier_lead_time_days=3,
    )
    bolt = Item(
        tenant_id=tenant_id,
        sku="RM-BOLT-8",
        name="Bolt M8x40",
        item_type="raw",
        unit_of_measure="boxes",
        reorder_point=50,
        supplier_lead_time_days=5,
    )
    widget = Item(
        tenant_id=tenant_id,
        sku="WIDGET-A",
        name="Widget A",
        item_type="finished",
        unit_of_measure="units",
        reorder_point=200,
        supplier_lead_time_days=2,
        bill_of_materials={"RM-STEEL-1": 2, "RM-BOLT-8": 4},
    )
    db.add_all([steel, bolt, widget])
    await db.flush()

    movements = []
    # Steel: 5 days of ~450/day consumption trending toward 1,240 on hand —
    # days_to_runout (~2.8d) falls inside the 3-day supplier lead time, so
    # this trips the low-stock/run-out alert exactly as the BRD example does.
    steel_qty = 3490.0
    for days_ago in (4, 3, 2, 1, 0):
        steel_qty -= 450.0
        movements.append(
            StockMovement(
                tenant_id=tenant_id, item_id=steel.id, timestamp=now - timedelta(days=days_ago),
                current_qty=steel_qty, qty_in=0, qty_out=450.0, movement_reason="Production consumption",
            )
        )

    # Bolt: healthy, well above reorder point.
    movements.append(
        StockMovement(
            tenant_id=tenant_id, item_id=bolt.id, timestamp=now - timedelta(days=1),
            current_qty=820.0, qty_in=0, qty_out=40.0, movement_reason="Production consumption",
        )
    )
    movements.append(
        StockMovement(
            tenant_id=tenant_id, item_id=bolt.id, timestamp=now,
            current_qty=780.0, qty_in=0, qty_out=40.0, movement_reason="Production consumption",
        )
    )

    # Widget A: healthy finished-goods stock.
    movements.append(
        StockMovement(
            tenant_id=tenant_id, item_id=widget.id, timestamp=now - timedelta(days=1),
            current_qty=640.0, qty_in=200, qty_out=60.0, movement_reason="Shipment out",
        )
    )
    movements.append(
        StockMovement(
            tenant_id=tenant_id, item_id=widget.id, timestamp=now,
            current_qty=590.0, qty_in=0, qty_out=50.0, movement_reason="Shipment out",
        )
    )

    db.add_all(movements)
    await db.commit()

    from app.core.ingestion import touch_freshness
    await touch_freshness(db, tenant_id, "inventory")

    return {"items_seeded": ["RM-STEEL-1", "RM-BOLT-8", "WIDGET-A"], "movements_seeded": len(movements)}

import React, { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

import { ApiError } from "../../api/client";
import { getDashboardSummary } from "../../api/dashboard";
import * as inventoryApi from "../../api/inventory";
import type { ItemInput, ItemWithProjection } from "../../api/inventory";
import { RoleGuard } from "../../auth/ProtectedRoute";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { FreshnessBadge } from "../../components/FreshnessBadge";
import { Skeleton } from "../../components/Loading";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { RowActions } from "../../components/RowActions";
import { Select } from "../../components/Select";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";
import { Tabs } from "../../components/Tabs";
import { ConfigImportTabs } from "../_shared/ConfigImportTabs";
import { FieldChips } from "../_shared/FieldChips";
import { FormSection } from "../_shared/FormSection";
import { QuickField, QuickLogForm } from "../_shared/QuickLogForm";

const STOCK_MOVEMENT_FIELDS = ["sku", "timestamp", "current_qty", "qty_in", "qty_out", "movement_reason"];
const ITEM_FIELDS = ["sku", "name", "item_type", "unit_of_measure", "reorder_point", "supplier_lead_time_days"];

// Plain `textTransform: capitalize` turns "wip" into "Wip" — WIP is an
// acronym (Work in Progress), not a word, so it needs its own explicit label
// rather than a generic CSS transform.
const ITEM_TYPE_LABEL: Record<ItemFormState["item_type"], string> = {
  raw: "Raw",
  wip: "WIP",
  finished: "Finished",
  "": "",
};

/** Tints ItemForm as an inset zone within its surrounding card (the Edit
 * block or the Add Items section's Manual Entry tab) — same treatment as
 * Production's LineForm and Predictive Maintenance's AssetForm. */
const quickAddCardStyle: React.CSSProperties = { background: "var(--color-neutral-100)", borderRadius: "var(--radius-lg)", padding: 16 };

/** Item quick-add/edit form state, kept as plain strings (including the
 * numeric fields) so every field can start genuinely empty — a real
 * ItemInput can't represent "no type chosen yet" or "no number typed yet". */
interface ItemFormState {
  sku: string;
  name: string;
  item_type: ItemInput["item_type"] | "";
  unit_of_measure: string;
  reorder_point: string;
  supplier_lead_time_days: string;
}

const EMPTY_FORM: ItemFormState = {
  sku: "",
  name: "",
  item_type: "",
  unit_of_measure: "",
  reorder_point: "",
  supplier_lead_time_days: "",
};

function itemToForm(item: ItemWithProjection): ItemFormState {
  return {
    sku: item.sku,
    name: item.name,
    item_type: item.item_type,
    unit_of_measure: item.unit_of_measure,
    reorder_point: String(item.reorder_point),
    supplier_lead_time_days: String(item.supplier_lead_time_days),
  };
}

/** One reusable, self-contained item form for both a fresh Add Items entry
 * and an existing item's Edit block — mirrors Production's LineForm and
 * Predictive Maintenance's AssetForm, so the three don't drift into
 * separate layouts/validations. */
function ItemForm({
  initial,
  initialBom = {},
  editing,
  items,
  excludeId,
  onCancel,
  onSave,
}: {
  initial: ItemFormState;
  initialBom?: Record<string, number>;
  editing?: boolean;
  items: ItemWithProjection[];
  /** The item currently being edited shouldn't be able to list itself as
   * its own BOM component. */
  excludeId?: number;
  onCancel: () => void;
  onSave: (payload: ItemInput) => Promise<void>;
}) {
  const [form, setForm] = useState<ItemFormState>(initial);
  const initialBomRows = useMemo(() => Object.entries(initialBom).map(([sku, qty]) => ({ sku, qty: String(qty) })), [initialBom]);
  const [bomRows, setBomRows] = useState<Array<{ sku: string; qty: string }>>(initialBomRows);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.item_type) return;
    setSaving(true);
    setError(null);
    try {
      // Only a finished good's rows actually get sent — switching Type away
      // from "Finished good" hides the section but leaves bomRows in state,
      // and a raw material/WIP item shouldn't pick up a leftover recipe.
      const bill_of_materials: Record<string, number> = {};
      if (form.item_type === "finished") {
        for (const row of bomRows) {
          if (row.sku.trim() && row.qty.trim()) bill_of_materials[row.sku.trim()] = Number(row.qty);
        }
      }
      await onSave({
        sku: form.sku.trim(),
        name: form.name.trim(),
        item_type: form.item_type,
        unit_of_measure: form.unit_of_measure.trim(),
        reorder_point: form.reorder_point === "" ? 0 : Number(form.reorder_point),
        supplier_lead_time_days: form.supplier_lead_time_days === "" ? 0 : Number(form.supplier_lead_time_days),
        bill_of_materials: Object.keys(bill_of_materials).length ? bill_of_materials : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Edit mode only: the Save button reads "Update" once something in the
  // form (or its BOM rows) actually differs from the item's current saved
  // values — same rule as LineForm/AssetForm's dirty check.
  const dirty = editing && (JSON.stringify(form) !== JSON.stringify(initial) || JSON.stringify(bomRows) !== JSON.stringify(initialBomRows));

  return (
    <div style={quickAddCardStyle}>
      <form onSubmit={handleSubmit} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        <QuickField label="Item Code">
          <input
            className="input"
            required
            placeholder="Item code (e.g. RM-1001)"
            value={form.sku}
            onChange={(e) => setForm({ ...form, sku: e.target.value })}
          />
        </QuickField>
        <QuickField label="Name">
          <input
            className="input"
            required
            placeholder="Name (e.g. Steel Rod 10mm)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </QuickField>
        <QuickField label="Type">
          <Select
            value={form.item_type}
            onChange={(e) => setForm({ ...form, item_type: e.target.value as ItemFormState["item_type"] })}
            placeholder="Select item type"
            options={[
              { value: "raw", label: "Raw material" },
              { value: "wip", label: "Work in Process (WIP)" },
              { value: "finished", label: "Finished good" },
            ]}
          />
        </QuickField>
        <QuickField label="Unit of Measure">
          <input
            className="input"
            placeholder="Unit of measure (e.g. kg)"
            value={form.unit_of_measure}
            onChange={(e) => setForm({ ...form, unit_of_measure: e.target.value })}
          />
        </QuickField>
        <QuickField label="Reorder Point">
          <input
            className="input"
            type="number"
            step="any"
            placeholder="Minimum stock level"
            value={form.reorder_point}
            onChange={(e) => setForm({ ...form, reorder_point: e.target.value })}
          />
        </QuickField>
        <QuickField label="Supplier Lead Time (Days)">
          <input
            className="input"
            type="number"
            placeholder="Days to deliver"
            value={form.supplier_lead_time_days}
            onChange={(e) => setForm({ ...form, supplier_lead_time_days: e.target.value })}
          />
        </QuickField>

        {form.item_type === "finished" && (
          <div style={{ gridColumn: "1 / -1" }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Bill of Materials</div>
            <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginTop: 2, marginBottom: 8 }}>
              What goes into one unit of this item, and how much of each.
            </div>
            {bomRows.map((row, i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                <Select
                  style={{ flex: 1 }}
                  value={row.sku}
                  onChange={(e) => setBomRows(bomRows.map((r, j) => (j === i ? { ...r, sku: e.target.value } : r)))}
                  options={items.filter((it) => it.id !== excludeId).map((it) => ({ value: it.sku, label: it.name }))}
                  placeholder="Item"
                />
                <input
                  className="input"
                  type="number"
                  step="any"
                  placeholder="Qty per unit"
                  value={row.qty}
                  onChange={(e) => setBomRows(bomRows.map((r, j) => (j === i ? { ...r, qty: e.target.value } : r)))}
                  style={{ width: 140 }}
                />
                <button
                  type="button"
                  onClick={() => setBomRows(bomRows.filter((_, j) => j !== i))}
                  className="btn-icon btn-icon--delete"
                  style={{ width: 42, height: 42 }}
                  aria-label="Remove component"
                  title="Remove component"
                >
                  <X size={14} strokeWidth={2} />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary"
              style={{ height: 42, padding: "0 20px" }}
              onClick={() => setBomRows([...bomRows, { sku: "", qty: "" }])}
            >
              + Add Component
            </button>
          </div>
        )}

        <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button className="btn-primary" style={{ minWidth: 160 }} type="submit" disabled={saving || !form.item_type}>
            {editing ? (saving ? "Saving..." : dirty ? "Update" : "Save") : saving ? "Adding..." : "Add Item"}
          </button>
        </div>
      </form>
      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 8 }}>{error}</div>}
    </div>
  );
}

/** One item's current stock logged for right now — the "quick daily form"
 * alternative to building a stock-movements CSV for a single row (PRD §4.9). */
function QuickStockLog({ items, onLogged }: { items: ItemWithProjection[]; onLogged: () => void }) {
  const [itemId, setItemId] = useState<number | "">("");
  const [qtyIn, setQtyIn] = useState("");
  const [qtyOut, setQtyOut] = useState("");
  const [reason, setReason] = useState("");

  const selectedItem = items.find((i) => i.id === itemId);

  return (
    <QuickLogForm
      submitLabel="Log Stock"
      syncEntity="inventory_movements"
      hideSuccessMessage
      disabled={!itemId || (!qtyIn && !qtyOut)}
      onSubmit={async () => {
        if (!itemId || !selectedItem) return;
        // Computed only at submit time — the item's on-hand quantity plus
        // what's coming in, minus what's going out — so the resulting
        // snapshot is right without the "Current qty" field itself having
        // to preview it live while the user is still typing.
        const newQty = (selectedItem.projection.current_qty ?? 0) + (Number(qtyIn) || 0) - (Number(qtyOut) || 0);
        await inventoryApi.quickLogStock(itemId, {
          current_qty: newQty,
          qty_in: qtyIn ? Number(qtyIn) : 0,
          qty_out: qtyOut ? Number(qtyOut) : 0,
          movement_reason: reason || null,
        });
      }}
      onSubmitted={() => {
        setItemId("");
        setQtyIn("");
        setQtyOut("");
        setReason("");
        onLogged();
      }}
    >
      <QuickField label="Item">
        <Select
          value={itemId}
          onChange={(e) => setItemId(Number(e.target.value))}
          options={items.map((i) => ({ value: i.id, label: `${i.name} (${i.sku})` }))}
          placeholder="Select item"
        />
      </QuickField>
      <QuickField label="Current qty">
        {/* Shows the item's on-hand quantity as of right now — stays put
            while qty in/out are being typed, and only reflects the movement
            once Log Stock actually runs and the item list refreshes. */}
        <div style={{ position: "relative" }}>
          <input
            className="input"
            type="number"
            value={selectedItem ? selectedItem.projection.current_qty ?? 0 : ""}
            disabled
            style={!selectedItem ? { color: "transparent", WebkitTextFillColor: "transparent" } : undefined}
          />
          {!selectedItem && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                paddingLeft: 12,
                fontSize: 13,
                color: "var(--color-text-tertiary)",
                pointerEvents: "none",
              }}
            >
              Current qty
            </div>
          )}
        </div>
      </QuickField>
      <QuickField label="Qty in">
        <input className="input" type="number" step="any" value={qtyIn} onChange={(e) => setQtyIn(e.target.value)} />
      </QuickField>
      <QuickField label="Qty out">
        <input className="input" type="number" step="any" value={qtyOut} onChange={(e) => setQtyOut(e.target.value)} />
      </QuickField>
      <QuickField label="Reason">
        <input
          className="input"
          placeholder="Reason (e.g. received shipment, damaged goods)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </QuickField>
    </QuickLogForm>
  );
}

type InventoryTab = "items" | "movements";

const TABS: Array<{ key: InventoryTab; label: string }> = [
  { key: "items", label: "Items" },
  { key: "movements", label: "Stock Movements" },
];

export default function InventoryPage() {
  const [tab, setTab] = useState<InventoryTab>("items");
  const [items, setItems] = useState<ItemWithProjection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [freshness, setFreshness] = useState<{ last_updated_at: string | null; is_stale: boolean; expected_cadence_hours: number | null } | null>(null);

  const [editingItem, setEditingItem] = useState<ItemWithProjection | null>(null);
  // Bumped after every manual "add item" save (or its Cancel) to remount
  // the Manual Entry form with a fresh, empty ItemForm instead of leaving
  // the just-submitted values sitting in the persistent tab.
  const [manualFormKey, setManualFormKey] = useState(0);

  // The edit form renders below the items table, out of view when the list
  // is long — without this, tapping Edit updates state but the user stays
  // scrolled wherever they already were and never sees the form appear.
  useEffect(() => {
    if (editingItem) {
      document.getElementById("inventory-edit-item")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [editingItem]);

  async function refresh() {
    try {
      const data = await inventoryApi.listItems();
      setItems(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load inventory");
    }
  }

  useEffect(() => {
    refresh();
    getDashboardSummary()
      .then((summaries) => {
        const s = summaries.find((x) => x.module === "inventory");
        if (s) setFreshness({ last_updated_at: s.last_updated_at, is_stale: s.is_stale, expected_cadence_hours: s.expected_cadence_hours });
      })
      .catch(() => undefined);
  }, []);

  const lowItems = useMemo(() => (items ?? []).filter((i) => i.projection.is_low), [items]);
  const mostUrgent = useMemo(
    () => [...lowItems].sort((a, b) => (a.projection.days_to_runout ?? Infinity) - (b.projection.days_to_runout ?? Infinity))[0],
    [lowItems]
  );

  async function handleUpdateItem(payload: ItemInput) {
    if (!editingItem) return;
    await inventoryApi.updateItem(editingItem.id, payload);
    setEditingItem(null);
    await refresh();
  }

  /** Manual Entry tab in the Add Items area — a plain create, kept separate
   * from handleUpdateItem (which handles editing an existing item from the
   * table) so the form can be remounted empty afterward instead of
   * closing/disappearing. */
  async function handleAddItem(payload: ItemInput) {
    await inventoryApi.createItem(payload);
    await refresh();
    setManualFormKey((k) => k + 1);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this item? Its stock movement history will also be removed.")) return;
    try {
      await inventoryApi.deleteItem(id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete item");
    }
  }

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="inventory" />}
        title="Inventory"
        subtitle="Stock availability monitoring and low-stock alerts."
        actions={
          <>
            {freshness && (
              <FreshnessBadge
                lastUpdatedAt={freshness.last_updated_at}
                isStale={freshness.is_stale}
                expectedCadenceHours={freshness.expected_cadence_hours}
                compact
              />
            )}
            {/* Redundant on the Stock Movements tab itself — you're already
                there. Kept as a jump-to shortcut from the Items tab. */}
            {tab !== "movements" && (
              <RoleGuard allow={["admin", "operator"]}>
                <button className="btn-primary" onClick={() => setTab("movements")}>
                  Upload Inventory Data
                </button>
              </RoleGuard>
            )}
          </>
        }
      />

      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginBottom: 12 }}>{error}</div>}

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as InventoryTab)} />

      {tab === "items" && (
        <div id="inventory-items-top">
          {lowItems.length > 0 && mostUrgent && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                background: "var(--color-warning-50)",
                border: "1px solid var(--color-warning-200)",
                borderRadius: "var(--radius-lg)",
                padding: "11px 16px",
                marginBottom: 12,
                marginTop: 10,
              }}
            >
              <span style={{ fontSize: 13, color: "var(--color-warning-800)", fontWeight: 600 }}>
                <span className="num">{lowItems.length}</span> item{lowItems.length === 1 ? " is" : "s are"} below reorder point.{" "}
                {mostUrgent.projection.days_to_runout !== null ? (
                  <>
                    <strong>{mostUrgent.name}</strong> has{" "}
                    {Math.round(mostUrgent.projection.days_to_runout) <= 0 ? (
                      "less than 1 day"
                    ) : (
                      <>
                        <strong className="num">{Math.round(mostUrgent.projection.days_to_runout)}</strong>{" "}
                        day{Math.round(mostUrgent.projection.days_to_runout) === 1 ? "" : "s"}
                      </>
                    )}{" "}
                    of supply remaining at{" "}
                    <span className="num">{mostUrgent.projection.daily_consumption}</span>/day, with a{" "}
                    <span className="num">{mostUrgent.supplier_lead_time_days}</span>-day supplier lead time.
                  </>
                ) : (
                  <strong>{mostUrgent.name}</strong>
                )}
              </span>
            </div>
          )}

          <RoleGuard allow={["operator", "viewer"]}>
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Item editing is Admin-only</span>
          </RoleGuard>

          {items === null ? (
            <Skeleton rows={4} />
          ) : items.length === 0 ? (
            <EmptyState title="No items configured" message="Add an item below to start tracking it." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Item Code</Th>
                  <Th>Item</Th>
                  <Th align="center">Type</Th>
                  <Th numeric align="center">Qty</Th>
                  <Th numeric align="center">Reorder</Th>
                  <Th numeric align="center">Rate (per day)</Th>
                  <Th align="center">Run-out</Th>
                  <Th align="center">Status</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </THead>
              <TBody>
                {items.map((item) => {
                  const critical = item.projection.days_to_runout !== null && item.projection.days_to_runout <= 1;
                  const bomEntries = item.bill_of_materials ? Object.entries(item.bill_of_materials) : [];
                  return (
                    <Tr key={item.id}>
                      <Td top>
                        <span style={{ fontWeight: 700, color: "var(--color-text-tertiary)" }} className="num">
                          {item.sku}
                        </span>
                      </Td>
                      <Td wrap top>
                        <span style={{ fontWeight: 600 }}>{item.name}</span>
                        {bomEntries.length > 0 && (
                          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                            {bomEntries
                              .map(([componentSku, qty]) => {
                                const component = items.find((i) => i.sku === componentSku);
                                return `${qty}× ${component ? component.name : componentSku}`;
                              })
                              .join(", ")}
                          </div>
                        )}
                      </Td>
                      <Td align="center" top>
                        <span style={{ color: "var(--color-text-secondary)" }}>{ITEM_TYPE_LABEL[item.item_type]}</span>
                      </Td>
                      <Td numeric align="center" top>
                        {item.projection.has_data ? (
                          <span style={{ fontWeight: 700 }}>{item.projection.current_qty}</span>
                        ) : (
                          <span style={{ color: "var(--color-text-tertiary)", fontWeight: 400 }}>no data yet</span>
                        )}
                      </Td>
                      <Td numeric align="center" top>
                        <span style={{ color: "var(--color-text-secondary)" }}>{item.reorder_point}</span>
                      </Td>
                      <Td numeric align="center" top>
                        <span style={{ color: "var(--color-text-secondary)" }}>{item.projection.daily_consumption}</span>
                      </Td>
                      <Td align="center" top>
                        {item.projection.runout_date && (
                          <span style={{ fontWeight: 600 }} className="num">
                            {item.projection.runout_date}
                          </span>
                        )}
                      </Td>
                      <Td align="center" top>
                        {item.projection.is_low ? (
                          <Badge variant={critical ? "critical" : "warning"}>{critical ? "Critical" : "Low"}</Badge>
                        ) : item.projection.has_data ? (
                          <Badge variant="ok">OK</Badge>
                        ) : null}
                      </Td>
                      <Td align="right" top>
                        <RoleGuard allow={["admin"]}>
                          <RowActions onEdit={() => setEditingItem(item)} onDelete={() => handleDelete(item.id)} />
                        </RoleGuard>
                      </Td>
                    </Tr>
                  );
                })}
              </TBody>
            </Table>
          )}

          <RoleGuard allow={["admin"]}>
            {editingItem && (
              <div id="inventory-edit-item" style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 15, marginBottom: 10 }}>Edit {editingItem.name}</h3>
                {/* Keyed on the item id so switching Edit from one item to
                    another remounts the form with fresh initial values —
                    same fix as Production's LineForm/AssetForm. */}
                <ItemForm
                  key={editingItem.id}
                  initial={itemToForm(editingItem)}
                  initialBom={editingItem.bill_of_materials ?? {}}
                  editing
                  items={items ?? []}
                  excludeId={editingItem.id}
                  onCancel={() => setEditingItem(null)}
                  onSave={handleUpdateItem}
                />
              </div>
            )}
          </RoleGuard>

          <RoleGuard allow={["admin"]}>
            <div style={{ marginTop: 24 }}>
              <FormSection
                title="Add Items"
                subtitle="Register the items you want to track stock levels for."
                collapsible
                defaultOpen={false}
              >
                <ConfigImportTabs
                  manual={
                    <ItemForm
                      key={manualFormKey}
                      initial={EMPTY_FORM}
                      items={items ?? []}
                      onCancel={() => setManualFormKey((k) => k + 1)}
                      onSave={handleAddItem}
                    />
                  }
                  csv={{
                    title: "Items",
                    hideHeading: true,
                    moduleLabel: "Inventory",
                    templatePath: inventoryApi.ITEM_CSV_PATHS.templatePath,
                    mapPath: inventoryApi.ITEM_CSV_PATHS.mapPath,
                    validatePath: inventoryApi.ITEM_CSV_PATHS.validatePath,
                    commitPath: inventoryApi.ITEM_CSV_PATHS.commitPath,
                    onCommitted: refresh,
                    syncEntity: "items",
                    fieldChips: <FieldChips fields={ITEM_FIELDS} />,
                  }}
                  db={{ entity: "items", title: "Items", moduleLabel: "Inventory", onCommitted: refresh }}
                />
              </FormSection>
            </div>
          </RoleGuard>
        </div>
      )}

      {tab === "movements" && (
        items && items.length > 0 ? (
          <RoleGuard allow={["admin", "operator"]}>
            <FormSection title="Stock Movements" subtitle="Each row records a single stock check-in or check-out for an item.">
              <ConfigImportTabs
                manual={<QuickStockLog items={items} onLogged={refresh} />}
                csv={{
                  title: "Stock Movements",
                  hideHeading: true,
                  moduleLabel: "Inventory",
                  templatePath: inventoryApi.STOCK_MOVEMENTS_CSV_PATHS.templatePath,
                  mapPath: inventoryApi.STOCK_MOVEMENTS_CSV_PATHS.mapPath,
                  validatePath: inventoryApi.STOCK_MOVEMENTS_CSV_PATHS.validatePath,
                  commitPath: inventoryApi.STOCK_MOVEMENTS_CSV_PATHS.commitPath,
                  onCommitted: refresh,
                  syncEntity: "inventory_movements",
                  fieldChips: <FieldChips fields={STOCK_MOVEMENT_FIELDS} />,
                }}
                db={{ entity: "inventory_movements", title: "Stock Movements", moduleLabel: "Inventory", onCommitted: refresh }}
              />
            </FormSection>
          </RoleGuard>
        ) : (
          <EmptyState title="No items configured" message="Configure an item on the Items tab first." />
        )
      )}
    </div>
  );
}

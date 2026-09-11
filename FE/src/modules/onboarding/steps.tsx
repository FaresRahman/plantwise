import React, { useEffect, useState } from "react";
import { Pencil, X } from "lucide-react";

import { inviteUser } from "../../api/admin";
import { OnboardingStepStatus } from "../../api/onboarding";
import * as pm from "../../api/predictiveMaintenance";
import { QuickMaintenanceLog, QuickReadingLog } from "../predictive-maintenance/PredictiveMaintenancePage";
import * as productionApi from "../../api/production";
import { OUTPUT_LOG_CSV_PATHS } from "../../api/production";
import * as inventoryApi from "../../api/inventory";
import * as qualityApi from "../../api/quality";
import { createShiftSchedule, deleteShiftSchedule, SCHEDULE_CSV_PATHS } from "../../api/shiftReports";
import { uploadSopDocument, uploadSopDocumentFromUrl } from "../../api/sop";
import { Select } from "../../components/Select";
import { BulkInviteForm } from "../_shared/BulkInviteForm";
import { ConfigImportTabs } from "../_shared/ConfigImportTabs";
import { CsvUploadFlow } from "../_shared/CsvUploadFlow";
import { DataSourceSetup } from "../_shared/DataSourceSetup";
import { QuickField } from "../_shared/QuickLogForm";

export interface OnboardingStep {
  key: string;
  title: string;
  component: React.ComponentType<{ onDataLoaded: () => void }>;
  isComplete: (status: OnboardingStepStatus[]) => boolean;
}

function statusFor(status: OnboardingStepStatus[], module: string): OnboardingStepStatus | undefined {
  return status.find((s) => s.module === module);
}

const rowStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8, marginBottom: 0 };
/** Marks a new data section within a step (e.g. "Sensor readings" below the
 * asset config above it) — a rule line first, since a label alone didn't
 * read as a hard break between the two areas. */
const sectionLabelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: ".04em",
  color: "var(--color-text-tertiary)",
  margin: "24px 0 10px",
  paddingTop: 18,
  borderTop: "1px solid var(--color-border-default)",
};
/** Wraps each step's quick-add form as a tinted inset zone — distinct from
 * the surrounding step card without stacking a second bordered/shadowed
 * card on top of it (the step card + this + the CSV upload card below all
 * competing for the same "card" treatment read as boxes-in-boxes). One shade
 * deeper than the step card's own background (--color-neutral-100 vs. the
 * card's --color-background-secondary) so the two are still distinguishable. */
const quickAddCardStyle: React.CSSProperties = { background: "var(--color-neutral-100)", borderRadius: "var(--radius-lg)", padding: 16, marginBottom: 6 };

interface AddedItem {
  id: number;
  label: string;
}

/** Renders items just added in a quick-add form as removable chips. This
 * used to be a plain "Added: X, Y" sentence with no way to undo a mistake —
 * each chip's × calls the real delete endpoint for that entity so a wrong
 * entry can be fixed right here instead of hunting for it on the full
 * module page later. `onEdit`/`editingId` are optional — only the
 * Predictive Maintenance step wires them up, since it's the only onboarding
 * step whose quick-add form doubles as an edit form (asset fields + its
 * metrics) once a chip's pencil is clicked. */
function AddedChips({
  items,
  onRemove,
  removingId,
  onEdit,
  editingId,
}: {
  items: AddedItem[];
  onRemove: (item: AddedItem) => void;
  removingId: number | null;
  onEdit?: (item: AddedItem) => void;
  editingId?: number | null;
}) {
  if (items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
      {items.map((item) => (
        <span
          key={item.id}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            background: "var(--color-success-50)",
            color: "var(--color-success-800)",
            border: editingId === item.id ? "1px solid var(--color-accent-500)" : "1px solid var(--color-success-200)",
            borderRadius: "var(--radius-full)",
            padding: onEdit ? "5px 6px 5px 12px" : "5px 6px 5px 12px",
            fontSize: 12.5,
            fontWeight: 600,
            opacity: removingId === item.id ? 0.5 : 1,
            transition: "opacity var(--transition-fast)",
          }}
        >
          {item.label}
          {onEdit && (
            <button
              type="button"
              onClick={() => onEdit(item)}
              disabled={removingId === item.id}
              title="Edit"
              aria-label={`Edit ${item.label}`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 18,
                height: 18,
                borderRadius: "50%",
                border: "1px solid var(--color-success-300)",
                background: "transparent",
                color: "var(--color-success-800)",
                cursor: removingId === item.id ? "not-allowed" : "pointer",
                padding: 0,
                flex: "none",
              }}
            >
              <Pencil size={10} strokeWidth={2.5} />
            </button>
          )}
          <button
            type="button"
            onClick={() => onRemove(item)}
            disabled={removingId === item.id}
            title="Remove (undo if this was added by mistake)"
            aria-label={`Remove ${item.label}`}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 18,
              height: 18,
              borderRadius: "50%",
              border: "1px solid var(--color-error-200)",
              background: "var(--color-error-50)",
              color: "var(--color-error-600)",
              cursor: removingId === item.id ? "not-allowed" : "pointer",
              padding: 0,
              flex: "none",
            }}
          >
            <X size={10} strokeWidth={2.5} />
          </button>
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Predictive Maintenance
// ---------------------------------------------------------------------------

interface MetricDraft {
  name: string;
  min: string;
  max: string;
  unit: string;
}

function emptyMetricDraft(): MetricDraft {
  return { name: "", min: "", max: "", unit: "" };
}

/** Most assets being registered are already installed and running today, so
 * defaulting to today saves a trip to the calendar for the common case —
 * mirrors the full Predictive Maintenance page's asset form. */
function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

function emptyPmForm(): pm.AssetIn {
  return { asset_code: "", name: "", category: "", line_area: "", criticality: "low", install_date: todayDateString() };
}

/** An asset's `monitored_metrics` map back into editable draft rows — used
 * both to seed the form when editing an already-added asset. Falls back to
 * one blank row (same as a brand-new asset) if it somehow has none, so the
 * "at least one metric" rule still has a row to fill in. */
function metricsToDrafts(monitored: Record<string, pm.MetricRange> | undefined): MetricDraft[] {
  const entries = Object.entries(monitored ?? {});
  if (entries.length === 0) return [emptyMetricDraft()];
  return entries.map(([name, range]) => ({ name, min: String(range.min), max: String(range.max), unit: range.unit ?? "" }));
}

function PmStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  const [form, setForm] = useState<pm.AssetIn>(emptyPmForm());
  // Every manually-added asset needs at least one normal range, or the
  // predictive-maintenance engine has nothing to compare readings against
  // and will never raise a recommendation/alert for it. An asset can have
  // more than one monitored metric (e.g. temperature AND pressure), so this
  // is a list — the extra rows are optional.
  const [metrics, setMetrics] = useState<MetricDraft[]>([emptyMetricDraft()]);
  const [saved, setSaved] = useState<AddedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assets, setAssets] = useState<pm.Asset[]>([]);
  // Set while the quick-add form is repurposed to edit an already-added
  // asset (clicked via the pencil on its chip) instead of creating a new
  // one — same form, same metric rows, just a different submit action.
  const [editingId, setEditingId] = useState<number | null>(null);

  async function refreshAssets() {
    try {
      setAssets(await pm.listAssets());
    } catch {
      /* ignore — the manual reading form just shows no assets yet */
    }
  }

  useEffect(() => {
    refreshAssets();
  }, []);

  function updateMetric(index: number, patch: Partial<MetricDraft>) {
    setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  }

  function addMetricRow() {
    setMetrics((prev) => [...prev, emptyMetricDraft()]);
  }

  function removeMetricRow(index: number) {
    setMetrics((prev) => (prev.length === 1 ? prev : prev.filter((_, i) => i !== index)));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!form.asset_code.trim() || !form.name.trim()) {
      setError("Asset code and name are required.");
      return;
    }

    // Blank extra rows (from "+ Add another metric") are just unused —
    // only rows the user actually touched need to be complete.
    const filledMetrics = metrics.filter((m) => m.name.trim() || m.min.trim() || m.max.trim() || m.unit.trim());
    if (filledMetrics.length === 0) {
      setError("Add a normal range for this asset — a metric with a min and max — so Plantwise can tell you when it's running outside it.");
      return;
    }
    const monitoredMetrics: Record<string, pm.MetricRange> = {};
    for (const m of filledMetrics) {
      if (!m.name.trim() || m.min.trim() === "" || m.max.trim() === "") {
        setError("Each normal range needs a metric name, a min, and a max.");
        return;
      }
      const min = Number(m.min);
      const max = Number(m.max);
      if (Number.isNaN(min) || Number.isNaN(max) || min >= max) {
        setError(`"${m.name.trim()}"'s min must be a number less than its max.`);
        return;
      }
      monitoredMetrics[m.name.trim()] = { min, max, unit: m.unit.trim() };
    }

    setSaving(true);
    try {
      if (editingId != null) {
        const asset = await pm.updateAsset(editingId, { ...form, monitored_metrics: monitoredMetrics });
        setSaved((prev) => prev.map((s) => (s.id === asset.id ? { id: asset.id, label: asset.asset_code } : s)));
        setEditingId(null);
      } else {
        const asset = await pm.createAsset({ ...form, monitored_metrics: monitoredMetrics });
        setSaved((prev) => [...prev, { id: asset.id, label: asset.asset_code }]);
      }
      setForm(emptyPmForm());
      setMetrics([emptyMetricDraft()]);
      await refreshAssets();
    } catch (err) {
      setError(err instanceof Error ? err.message : editingId != null ? "Failed to update asset" : "Failed to add asset");
    } finally {
      setSaving(false);
    }
  }

  function handleEdit(item: AddedItem) {
    const asset = assets.find((a) => a.id === item.id);
    if (!asset) return;
    setError(null);
    setEditingId(asset.id);
    setForm({ asset_code: asset.asset_code, name: asset.name, category: asset.category, line_area: asset.line_area, criticality: asset.criticality, install_date: asset.install_date ?? "" });
    setMetrics(metricsToDrafts(asset.monitored_metrics));
  }

  function handleCancelEdit() {
    setEditingId(null);
    setForm(emptyPmForm());
    setMetrics([emptyMetricDraft()]);
    setError(null);
  }

  async function handleRemove(item: AddedItem) {
    setRemovingId(item.id);
    try {
      await pm.deleteAsset(item.id);
      setSaved((prev) => prev.filter((s) => s.id !== item.id));
      if (editingId === item.id) handleCancelEdit();
      await refreshAssets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove asset");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
        Register assets for predictive maintenance to monitor, each with at least one normal range so Plantwise can
        tell you when a reading is out of bounds. Add more metrics or service intervals any time on the full module
        page.
      </p>
      <ConfigImportTabs
        manual={
          <div style={quickAddCardStyle}>
            <form onSubmit={handleAdd}>
              <div style={rowStyle}>
                <input className="input" placeholder="Asset code (e.g. CNC-04)" value={form.asset_code} onChange={(e) => setForm({ ...form, asset_code: e.target.value })} />
                <input className="input" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                <input className="input" placeholder="Category" value={form.category ?? ""} onChange={(e) => setForm({ ...form, category: e.target.value })} />
                <input className="input" placeholder="Line / area" value={form.line_area ?? ""} onChange={(e) => setForm({ ...form, line_area: e.target.value })} />
                <QuickField label="Criticality">
                  <Select
                    value={form.criticality ?? "low"}
                    onChange={(e) => setForm({ ...form, criticality: e.target.value as pm.AssetIn["criticality"] })}
                    options={[
                      { value: "low", label: "Low criticality" },
                      { value: "med", label: "Medium criticality" },
                      { value: "high", label: "High criticality" },
                    ]}
                  />
                </QuickField>
                <QuickField label="Install date">
                  <input className="input" type="date" value={form.install_date ?? ""} onChange={(e) => setForm({ ...form, install_date: e.target.value })} />
                </QuickField>
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, marginTop: 16, marginBottom: 4 }}>Normal range</div>
              <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginBottom: 10, lineHeight: 1.4 }}>
                The safe range for each metric you want this asset monitored on. You can add ranges for more metrics,
                or fix one later by editing this asset.
              </div>
              {metrics.map((m, i) => (
                <div key={i} style={{ ...rowStyle, marginTop: 8, alignItems: "center" }}>
                  <input className="input" placeholder="Metric (e.g. vibration)" value={m.name} onChange={(e) => updateMetric(i, { name: e.target.value })} />
                  <QuickField label="Normal min">
                    <input className="input" type="number" value={m.min} onChange={(e) => updateMetric(i, { min: e.target.value })} />
                  </QuickField>
                  <QuickField label="Normal max">
                    <input className="input" type="number" value={m.max} onChange={(e) => updateMetric(i, { max: e.target.value })} />
                  </QuickField>
                  <input className="input" placeholder="Unit (e.g. mm/s)" value={m.unit} onChange={(e) => updateMetric(i, { unit: e.target.value })} />
                  {metrics.length > 1 && (
                    <button
                      type="button"
                      className="btn-icon btn-icon--delete"
                      onClick={() => removeMetricRow(i)}
                      aria-label="Remove this metric"
                      title="Remove this metric"
                      style={{ width: 42, height: 42, flex: "none" }}
                    >
                      <X size={14} strokeWidth={2} />
                    </button>
                  )}
                </div>
              ))}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
                <button type="button" className="btn-ghost" onClick={addMetricRow} style={{ fontSize: 12.5, padding: "6px 0", height: "auto", minWidth: 0 }}>
                  + Add another metric
                </button>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  {editingId != null && (
                    <button type="button" className="btn-ghost" onClick={handleCancelEdit} style={{ fontSize: 13 }}>
                      Cancel
                    </button>
                  )}
                  <button className="btn-primary" type="submit" disabled={saving}>
                    {saving ? (editingId != null ? "Saving..." : "Adding...") : editingId != null ? "Save changes" : "+ Add asset"}
                  </button>
                </div>
              </div>
            </form>
            {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
            <AddedChips items={saved} onRemove={handleRemove} removingId={removingId} onEdit={handleEdit} editingId={editingId} />
          </div>
        }
        csv={{
          onCommitted: onDataLoaded,
          title: "Assets",
          moduleLabel: "Predictive Maintenance",
          templatePath: pm.ASSET_CSV_PATHS.template,
          mapPath: pm.ASSET_CSV_PATHS.map,
          validatePath: pm.ASSET_CSV_PATHS.validate,
          commitPath: pm.ASSET_CSV_PATHS.commit,
          embedded: true,
        }}
      />

      <div style={sectionLabelStyle}>Sensor readings</div>
      {assets.length === 0 ? (
        <p style={{ fontSize: 12.5, color: "var(--color-text-tertiary)" }}>Add an asset above first, then you can log its readings here.</p>
      ) : (
        <ConfigImportTabs
          manual={<QuickReadingLog assets={assets} onLogged={onDataLoaded} />}
          csv={{
            onCommitted: onDataLoaded,
            title: "Sensor Readings",
            moduleLabel: "Predictive Maintenance",
            templatePath: pm.READINGS_CSV_PATHS.template,
            mapPath: pm.READINGS_CSV_PATHS.map,
            validatePath: pm.READINGS_CSV_PATHS.validate,
            commitPath: pm.READINGS_CSV_PATHS.commit,
            embedded: true,
          }}
        />
      )}

      <div style={sectionLabelStyle}>Maintenance history</div>
      {assets.length === 0 ? (
        <p style={{ fontSize: 12.5, color: "var(--color-text-tertiary)" }}>Add an asset above first, then you can log its service history here.</p>
      ) : (
        <ConfigImportTabs
          manual={<QuickMaintenanceLog assets={assets} onLogged={onDataLoaded} />}
          csv={{
            onCommitted: onDataLoaded,
            title: "Maintenance History",
            moduleLabel: "Predictive Maintenance",
            templatePath: pm.MAINTENANCE_CSV_PATHS.template,
            mapPath: pm.MAINTENANCE_CSV_PATHS.map,
            validatePath: pm.MAINTENANCE_CSV_PATHS.validate,
            commitPath: pm.MAINTENANCE_CSV_PATHS.commit,
            embedded: true,
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Production
// ---------------------------------------------------------------------------

const EMPTY_LINE_FORM: productionApi.LineInput = { line_code: "", name: "", stations: [], products: [], shift_target_units: 0, ideal_cycle_time_seconds: 0 };

function ProductionStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  // Typed directly against LineInput (the full Production page's create
  // form does the same) so a future field added there fails to compile here
  // instead of silently drifting out of sync.
  const [form, setForm] = useState<productionApi.LineInput>(EMPTY_LINE_FORM);
  // Stations/products/numeric fields are edited as raw text, separate from
  // the typed form, so an untouched field renders empty (with its
  // placeholder visible) instead of "0", and parsing only happens at submit
  // time — same pattern as the full page's line form.
  const [stationsText, setStationsText] = useState("");
  const [productsText, setProductsText] = useState("");
  const [shiftTargetInput, setShiftTargetInput] = useState("");
  const [cycleTimeInput, setCycleTimeInput] = useState("");
  const [saved, setSaved] = useState<AddedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: productionApi.LineInput = {
        ...form,
        stations: stationsText.split(/[,;]/).map((s) => s.trim()).filter(Boolean),
        products: productsText.split(/[,;]/).map((s) => s.trim()).filter(Boolean),
        shift_target_units: shiftTargetInput === "" ? 0 : Number(shiftTargetInput),
        ideal_cycle_time_seconds: cycleTimeInput === "" ? 0 : Number(cycleTimeInput),
      };
      const line = await productionApi.createLine(payload);
      setSaved((prev) => [...prev, { id: line.id, label: line.line_code }]);
      setForm(EMPTY_LINE_FORM);
      setStationsText("");
      setProductsText("");
      setShiftTargetInput("");
      setCycleTimeInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add line");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(item: AddedItem) {
    setRemovingId(item.id);
    try {
      await productionApi.deleteLine(item.id);
      setSaved((prev) => prev.filter((s) => s.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove line");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Configure a production line and its shift target.</p>
      <ConfigImportTabs
        manual={
          <div style={quickAddCardStyle}>
            <form onSubmit={handleAdd} style={rowStyle}>
              <input className="input" placeholder="Line code (e.g. LINE-2)" value={form.line_code} onChange={(e) => setForm({ ...form, line_code: e.target.value })} required />
              <input className="input" placeholder="Name (e.g. Bottling Line)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <QuickField label="Stations (comma-separated)">
                <input className="input" placeholder="Stations, comma-separated (e.g. Station 1, Station 2)" value={stationsText} onChange={(e) => setStationsText(e.target.value)} />
              </QuickField>
              <input className="input" placeholder="Products (comma-separated, e.g. Water Bottle, Juice Bottle)" value={productsText} onChange={(e) => setProductsText(e.target.value)} />
              <QuickField label="Shift target (units)">
                <input className="input num" type="number" value={shiftTargetInput} onChange={(e) => setShiftTargetInput(e.target.value)} />
              </QuickField>
              <QuickField label="Ideal cycle time (s)">
                <input className="input num" type="number" step="any" value={cycleTimeInput} onChange={(e) => setCycleTimeInput(e.target.value)} />
              </QuickField>
              <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? "Adding..." : "+ Add line"}
                </button>
              </div>
            </form>
            {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
            <AddedChips items={saved} onRemove={handleRemove} removingId={removingId} />
          </div>
        }
        csv={{
          onCommitted: onDataLoaded,
          title: "Lines",
          moduleLabel: "Production",
          ...productionApi.LINE_CSV_PATHS,
          embedded: true,
        }}
      />

      <div style={sectionLabelStyle}>Production output</div>
      <CsvUploadFlow
        onCommitted={onDataLoaded}
        title="Production Output"
        moduleLabel="Production"
        {...OUTPUT_LOG_CSV_PATHS}
        embedded
      />

    </div>
  );
}

// ---------------------------------------------------------------------------
// Inventory
// ---------------------------------------------------------------------------

function InventoryStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  const [form, setForm] = useState<inventoryApi.ItemInput>({ sku: "", name: "", item_type: "raw", unit_of_measure: "", reorder_point: 0, supplier_lead_time_days: 0, bill_of_materials: null });
  // Kept as raw strings, separate from `form`, so an untouched field renders
  // truly empty (with its placeholder visible) instead of showing "0".
  const [reorderPointInput, setReorderPointInput] = useState("");
  const [leadTimeInput, setLeadTimeInput] = useState("");
  const [saved, setSaved] = useState<AddedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const item = await inventoryApi.createItem({
        ...form,
        reorder_point: reorderPointInput === "" ? 0 : Number(reorderPointInput),
        supplier_lead_time_days: leadTimeInput === "" ? 0 : Number(leadTimeInput),
      });
      setSaved((prev) => [...prev, { id: item.id, label: item.sku }]);
      setForm({ sku: "", name: "", item_type: "raw", unit_of_measure: "", reorder_point: 0, supplier_lead_time_days: 0, bill_of_materials: null });
      setReorderPointInput("");
      setLeadTimeInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add item");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(item: AddedItem) {
    setRemovingId(item.id);
    try {
      await inventoryApi.deleteItem(item.id);
      setSaved((prev) => prev.filter((s) => s.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove item");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
        Register items to track stock for. Add a bill-of-materials for finished goods on the full module page.
      </p>
      <ConfigImportTabs
        manual={
          <div style={quickAddCardStyle}>
            <form onSubmit={handleAdd} style={rowStyle}>
              <input className="input" placeholder="Item code (e.g. RM-1001)" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} required />
              <input className="input" placeholder="Name (e.g. Steel Rod 10mm)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <Select
                value={form.item_type}
                onChange={(e) => setForm({ ...form, item_type: e.target.value as inventoryApi.ItemInput["item_type"] })}
                options={[
                  { value: "raw", label: "Raw material" },
                  { value: "wip", label: "Work in Process (WIP)" },
                  { value: "finished", label: "Finished good" },
                ]}
              />
              <input className="input" placeholder="Unit of measure (e.g. kg)" value={form.unit_of_measure} onChange={(e) => setForm({ ...form, unit_of_measure: e.target.value })} />
              <QuickField label="Reorder point">
                <input className="input num" type="number" placeholder="Minimum stock level" value={reorderPointInput} onChange={(e) => setReorderPointInput(e.target.value)} />
              </QuickField>
              <QuickField label="Lead time (days)">
                <input className="input num" type="number" placeholder="Days to deliver" value={leadTimeInput} onChange={(e) => setLeadTimeInput(e.target.value)} />
              </QuickField>
              <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? "Adding..." : "+ Add item"}
                </button>
              </div>
            </form>
            {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
            <AddedChips items={saved} onRemove={handleRemove} removingId={removingId} />
          </div>
        }
        csv={{
          ...inventoryApi.ITEM_CSV_PATHS,
          onCommitted: onDataLoaded,
          title: "Items",
          moduleLabel: "Inventory",
          embedded: true,
        }}
      />

      <div style={sectionLabelStyle}>Stock movements</div>
      <CsvUploadFlow
        onCommitted={onDataLoaded}
        title="Stock Movements"
        moduleLabel="Inventory"
        {...inventoryApi.STOCK_MOVEMENTS_CSV_PATHS}
        embedded
      />

    </div>
  );
}

// ---------------------------------------------------------------------------
// Quality
// ---------------------------------------------------------------------------

function QualityStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  const [form, setForm] = useState<qualityApi.CharacteristicIn>({ part_id: "", characteristic_name: "", nominal_value: 0, tolerance: 0, inspection_type: "", line_id: "", station_id: "", defect_categories: [] });
  // Kept as raw strings, separate from `form`, so an untouched field renders
  // truly empty (with its placeholder visible) instead of showing "0".
  const [nominalInput, setNominalInput] = useState("");
  const [toleranceInput, setToleranceInput] = useState("");
  const [saved, setSaved] = useState<AddedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // So Line/Station are picked from what's already registered in the
  // Production step instead of retyped — the step chips let this step be
  // reached before or after Production, so lines may not exist yet.
  const [lines, setLines] = useState<productionApi.Line[]>([]);

  useEffect(() => {
    productionApi.getLines().then(setLines).catch(() => setLines([]));
  }, []);

  const selectedLine = lines.find((l) => l.line_code === form.line_id);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (nominalInput.trim() === "" || toleranceInput.trim() === "") {
      setError("Nominal value and tolerance are required.");
      return;
    }
    setSaving(true);
    try {
      const char = await qualityApi.createCharacteristic({
        ...form,
        nominal_value: Number(nominalInput),
        tolerance: Number(toleranceInput),
      });
      setSaved((prev) => [...prev, { id: char.id, label: `${char.part_id}/${char.characteristic_name}` }]);
      setForm({ part_id: "", characteristic_name: "", nominal_value: 0, tolerance: 0, inspection_type: "", line_id: "", station_id: "", defect_categories: [] });
      setNominalInput("");
      setToleranceInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add characteristic");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(item: AddedItem) {
    setRemovingId(item.id);
    try {
      await qualityApi.deleteCharacteristic(item.id);
      setSaved((prev) => prev.filter((s) => s.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove characteristic");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Define a quality characteristic you inspect for.</p>
      <ConfigImportTabs
        manual={
          <div style={quickAddCardStyle}>
            <form onSubmit={handleAdd} style={rowStyle}>
              <input className="input" placeholder="Part ID (e.g. PN-1042)" value={form.part_id} onChange={(e) => setForm({ ...form, part_id: e.target.value })} required />
              <input className="input" placeholder="Characteristic name (e.g. Bore Diameter)" value={form.characteristic_name} onChange={(e) => setForm({ ...form, characteristic_name: e.target.value })} required />
              <QuickField label="Nominal value">
                <input className="input num" type="number" step="any" placeholder="e.g. 25.4" value={nominalInput} onChange={(e) => setNominalInput(e.target.value)} />
              </QuickField>
              <QuickField label="Tolerance (±)">
                <input className="input num" type="number" step="any" placeholder="e.g. 0.05" value={toleranceInput} onChange={(e) => setToleranceInput(e.target.value)} />
              </QuickField>
              <Select
                value={form.line_id}
                onChange={(e) => setForm({ ...form, line_id: e.target.value, station_id: "" })}
                options={lines.map((l) => ({ value: l.line_code, label: l.name }))}
                placeholder={lines.length === 0 ? "No lines yet — add one above" : "Line (optional)"}
              />
              <Select
                value={form.station_id}
                onChange={(e) => setForm({ ...form, station_id: e.target.value })}
                options={(selectedLine?.stations ?? []).map((s) => ({ value: s, label: s }))}
                placeholder={selectedLine ? "Station (optional)" : "Pick a line first"}
              />
              <input className="input" placeholder="Inspection type (e.g. Caliper)" value={form.inspection_type} onChange={(e) => setForm({ ...form, inspection_type: e.target.value })} />
              <input
                className="input"
                placeholder="Defect categories (comma-separated, e.g. Scratch, Dent, Discoloration)"
                value={form.defect_categories.join(", ")}
                onChange={(e) =>
                  setForm({
                    ...form,
                    defect_categories: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  })
                }
              />
              <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? "Adding..." : "+ Add spec"}
                </button>
              </div>
            </form>
            {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
            <AddedChips items={saved} onRemove={handleRemove} removingId={removingId} />
          </div>
        }
        csv={{
          ...qualityApi.CHARACTERISTIC_CSV_PATHS,
          onCommitted: onDataLoaded,
          title: "Characteristics",
          moduleLabel: "Quality",
          embedded: true,
        }}
      />

      <div style={sectionLabelStyle}>Inspection records</div>
      <CsvUploadFlow
        onCommitted={onDataLoaded}
        title="Inspection Records"
        moduleLabel="Quality"
        {...qualityApi.INSPECTION_RECORDS_CSV_PATHS}
        embedded
      />

    </div>
  );
}

// ---------------------------------------------------------------------------
// SOP
// ---------------------------------------------------------------------------

function SopStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [tags, setTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<string[]>([]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    setUploading(true);
    setUploadError(null);
    try {
      if (uploadMode === "file") {
        if (!file) return;
        const doc = await uploadSopDocument(file, "", tags);
        setUploaded((prev) => [...prev, doc.name]);
        setFile(null);
      } else {
        if (!url.trim()) return;
        const doc = await uploadSopDocumentFromUrl(url.trim(), "", tags);
        setUploaded((prev) => [...prev, doc.name]);
        setUrl("");
      }
      setTags("");
      onDataLoaded();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
        Upload SOPs, manuals, or safety procedures (PDF/DOCX) so the chatbot can answer "how do I…" questions with
        citations. Documents are named after their file by default — rename them or add more from SOP Library.
      </p>
      <div style={quickAddCardStyle}>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          {(["file", "url"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setUploadMode(mode)}
              className={uploadMode === mode ? "seg-btn seg-btn--active" : "seg-btn"}
            >
              {mode === "file" ? "File" : "URL"}
            </button>
          ))}
        </div>
        <form onSubmit={handleUpload} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {uploadMode === "file" ? (
            <label className="btn-secondary" style={{ fontSize: 13 }}>
              {file ? file.name : "Choose file (PDF, DOCX, TXT, MD)"}
              <input
                type="file"
                accept=".pdf,.docx,.txt,.md"
                style={{ display: "none" }}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
          ) : (
            <input
              className="input"
              type="url"
              placeholder="URL (e.g. https://example.com/sop.pdf)"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              style={{ flex: "1 1 240px" }}
            />
          )}
          <input className="input" placeholder="Tags (e.g. maintenance, safety)" value={tags} onChange={(e) => setTags(e.target.value)} style={{ maxWidth: 220 }} />
          <button className="btn-primary" type="submit" disabled={uploading || (uploadMode === "file" ? !file : !url.trim())}>
            {uploading ? "Uploading..." : "Upload document"}
          </button>
        </form>
        {uploadError && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{uploadError}</p>}
        {uploaded.length > 0 && <p style={{ fontSize: 13, color: "var(--color-success-700)", margin: "8px 0 0" }}>Uploaded: {uploaded.join(", ")}</p>}
      </div>

    </div>
  );
}

// ---------------------------------------------------------------------------
// Shift schedule
// ---------------------------------------------------------------------------

function ShiftScheduleStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  const [form, setForm] = useState({ name: "", start_time: "06:00", end_time: "14:00", areas: "", recipients: "" });
  const [saved, setSaved] = useState<AddedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const schedule = await createShiftSchedule({
        name: form.name,
        start_time: form.start_time,
        end_time: form.end_time,
        areas: form.areas.split(",").map((s) => s.trim()).filter(Boolean),
        recipients: form.recipients.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setSaved((prev) => [...prev, { id: schedule.id, label: schedule.name }]);
      setForm({ name: "", start_time: "06:00", end_time: "14:00", areas: "", recipients: "" });
      onDataLoaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add shift schedule");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(item: AddedItem) {
    if (!window.confirm(`Remove the "${item.label}" shift schedule? This can't be undone.`)) return;
    setRemovingId(item.id);
    try {
      await deleteShiftSchedule(item.id);
      setSaved((prev) => prev.filter((s) => s.id !== item.id));
      onDataLoaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove shift schedule");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
        Set up your shift schedule so handover reports generate automatically at shift end.
      </p>
      <ConfigImportTabs
        manual={
          <div style={quickAddCardStyle}>
            <form onSubmit={handleAdd} style={rowStyle}>
              <input className="input" placeholder="Name (e.g. Day Shift)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              {/* Native time inputs never render `placeholder` — an explicit
                  caption is the only way this field gets a visible hint,
                  matching what the full page's labeled time picker conveys. */}
              <div>
                <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginBottom: 4 }}>Start time</div>
                <input className="input" type="time" aria-label="Start time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} required />
              </div>
              <div>
                <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginBottom: 4 }}>End time</div>
                <input className="input" type="time" aria-label="End time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} required />
              </div>
              <QuickField label="Lines/areas (comma-separated)">
                <input className="input" placeholder="Areas (e.g. Line 2, Line 3)" value={form.areas} onChange={(e) => setForm({ ...form, areas: e.target.value })} />
              </QuickField>
              <QuickField label="Report recipients (comma-separated emails)" style={{ gridColumn: "span 2" }}>
                <input className="input" placeholder="Recipients (e.g. supervisor@plant.com)" value={form.recipients} onChange={(e) => setForm({ ...form, recipients: e.target.value })} />
              </QuickField>
              <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? "Adding..." : "+ Add shift"}
                </button>
              </div>
            </form>
            {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
            <AddedChips items={saved} onRemove={handleRemove} removingId={removingId} />
          </div>
        }
        csv={{
          onCommitted: onDataLoaded,
          title: "Shift Schedules",
          moduleLabel: "Shift Reports",
          ...SCHEDULE_CSV_PATHS,
          embedded: true,
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Invite team
// ---------------------------------------------------------------------------

function InviteTeamStep() {
  const [form, setForm] = useState({ email: "", full_name: "", role: "operator" });
  const [invited, setInvited] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bulkMode, setBulkMode] = useState(false);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const user = await inviteUser(form);
      setInvited((prev) => [...prev, user.email]);
      setForm({ email: "", full_name: "", role: "operator" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to invite teammate");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)", margin: 0 }}>
          Invite your Operators and Viewers so they can start using the dashboard and chatbot.
        </p>
        <button type="button" className="btn-secondary" style={{ fontSize: 12, padding: "6px 12px", flex: "none" }} onClick={() => setBulkMode((v) => !v)}>
          {bulkMode ? "Invite one at a time instead" : "Invite several at once"}
        </button>
      </div>
      <div style={quickAddCardStyle}>
        {bulkMode ? (
          <BulkInviteForm roles={["operator", "viewer", "admin"]} />
        ) : (
          <form onSubmit={handleInvite} style={rowStyle}>
            <input className="input" type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <input className="input" placeholder="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
            <Select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              options={[
                { value: "operator", label: "Operator" },
                { value: "viewer", label: "Viewer" },
              ]}
            />
            <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end" }}>
              <button className="btn-primary" type="submit" disabled={saving}>
                {saving ? "Inviting..." : "+ Invite teammate"}
              </button>
            </div>
          </form>
        )}
        {error && <p style={{ fontSize: 13, color: "var(--color-error-600)", margin: "8px 0 0" }}>{error}</p>}
        {invited.length > 0 && <p style={{ fontSize: 13, color: "var(--color-success-700)", margin: "8px 0 0" }}>Invited: {invited.join(", ")}</p>}
      </div>
    </div>
  );
}

/** The recommended path: connect one database, map whichever of the 9
 * entities it has, each starts syncing automatically. Always "complete" (like
 * inviting the team) — the user isn't forced to map everything before moving
 * on, and each mapped entity's real module step already reflects its own
 * completion via ModuleFreshness the moment sync lands data. */
function DatabaseSyncStep({ onDataLoaded }: { onDataLoaded: () => void }) {
  return <DataSourceSetup embedded onEntityMapped={onDataLoaded} />;
}

/**
 * Append-only, same convention as nav.ts/routes.tsx — one entry per module.
 * Each step embeds the module's real quick-add config form + CSV upload flow
 * inline (BRD §5.1/§6.1: "fill the config form, download the CSV template,
 * upload operational data — or click Load sample data", all inside the
 * wizard, not a link out to go do it elsewhere).
 *
 * Used for the "Enter Data Manually" path chosen on the Data Source step —
 * see OnboardingPage.tsx, which picks between this and
 * DATABASE_ONBOARDING_STEPS based on that choice.
 */
export const MANUAL_ONBOARDING_STEPS: OnboardingStep[] = [
  { key: "predictive_maintenance", title: "Predictive Maintenance", component: PmStep, isComplete: (status) => statusFor(status, "predictive_maintenance")?.complete ?? false },
  { key: "production", title: "Production", component: ProductionStep, isComplete: (status) => statusFor(status, "production")?.complete ?? false },
  { key: "inventory", title: "Inventory", component: InventoryStep, isComplete: (status) => statusFor(status, "inventory")?.complete ?? false },
  { key: "quality", title: "Quality", component: QualityStep, isComplete: (status) => statusFor(status, "quality")?.complete ?? false },
  { key: "sop", title: "SOP Library", component: SopStep, isComplete: (status) => statusFor(status, "sop")?.complete ?? false },
  { key: "shift_reports", title: "Shift Reports", component: ShiftScheduleStep, isComplete: (status) => statusFor(status, "shift_reports")?.complete ?? false },
  { key: "invite_team", title: "Invite your team (optional)", component: InviteTeamStep, isComplete: () => true },
];

/** The "Automate with Database Sync" path — one consolidated connect+map
 * step replaces the five per-module config/data steps above (their
 * completion still reads correctly the moment sync lands data). SOP
 * documents aren't sync-able data, so that step stays as-is; inviting the
 * team is unrelated to the data source either way. */
export const DATABASE_ONBOARDING_STEPS: OnboardingStep[] = [
  { key: "database_sync", title: "Connect & Map Your Database", component: DatabaseSyncStep, isComplete: () => true },
  { key: "sop", title: "SOP Library", component: SopStep, isComplete: (status) => statusFor(status, "sop")?.complete ?? false },
  { key: "invite_team", title: "Invite your team (optional)", component: InviteTeamStep, isComplete: () => true },
];

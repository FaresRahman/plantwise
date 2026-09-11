import React, { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { X } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getDashboardSummary } from "../../api/dashboard";
import * as pm from "../../api/predictiveMaintenance";
import { getLines, Line as ProductionLine } from "../../api/production";
import { RoleGuard } from "../../auth/ProtectedRoute";
import { Badge, urgencyVariant } from "../../components/Badge";
import { DrillDownModal } from "../../components/DrillDownModal";
import { EmptyState } from "../../components/EmptyState";
import { FreshnessBadge } from "../../components/FreshnessBadge";
import { Skeleton } from "../../components/Loading";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { RowActions } from "../../components/RowActions";
import { Select } from "../../components/Select";
import { Table, TBody, Td, THead, Th, Tr } from "../../components/Table";
import { Tabs } from "../../components/Tabs";
import { ConfigImportTabs } from "../_shared/ConfigImportTabs";
import { CsvUploadFlow } from "../_shared/CsvUploadFlow";
import { FieldChips } from "../_shared/FieldChips";
import { FormSection } from "../_shared/FormSection";
import { QuickField, QuickLogForm } from "../_shared/QuickLogForm";
import { useActiveSyncSchedule, useIsDbConnected } from "../_shared/useSyncStatus";

const URGENCY_ORDER: Record<pm.Urgency, number> = { high: 0, med: 1, low: 2 };
/** Accent bar color for the recommendation row's left edge — the urgency
 * pill itself is rendered via the shared Badge component. */
const URGENCY_BAR: Record<pm.Urgency, string> = {
  high: "var(--color-error-500)",
  med: "var(--color-warning-500)",
  low: "var(--color-info-500)",
};
/** Plain-word urgency reads next to the asset name — the colored left bar
 * (URGENCY_BAR above) already carries the severity, so this doesn't repeat
 * the raw "high"/"med"/"low" enum, it names the action it implies instead. */
const URGENCY_LABEL: Record<pm.Urgency, string> = { high: "Immediate", med: "Soon", low: "Monitor" };
const URGENCY_TEXT: Record<pm.Urgency, string> = {
  high: "var(--color-error-700)",
  med: "var(--color-warning-700)",
  low: "var(--color-info-700)",
};
/** Full-word labels for the criticality chip — the raw "med" enum value read
 * as a typo/abbreviation in the table, not a real severity level. */
const CRITICALITY_LABEL: Record<pm.Asset["criticality"], string> = { low: "Low", med: "Medium", high: "High" };

type AssetFormState = {
  asset_code: string;
  name: string;
  category: string;
  line_area: string;
  criticality: "" | "low" | "med" | "high";
  install_date: string;
  metrics: Array<{ metric: string; min: string; max: string; unit: string }>;
};

/** Most assets being registered are already installed and running today, so
 * defaulting to today saves a trip to the calendar for the common case —
 * still fully editable for the (rarer) case of a known past install date. */
function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

function makeEmptyForm(): AssetFormState {
  return {
    asset_code: "",
    name: "",
    category: "",
    line_area: "",
    criticality: "",
    install_date: todayDateString(),
    metrics: [{ metric: "", min: "", max: "", unit: "" }],
  };
}

function assetToForm(asset: pm.Asset): AssetFormState {
  return {
    asset_code: asset.asset_code,
    name: asset.name,
    category: asset.category,
    line_area: asset.line_area,
    criticality: asset.criticality,
    install_date: asset.install_date ?? "",
    metrics: Object.entries(asset.monitored_metrics).map(([metric, range]) => ({
      metric,
      min: String(range.min),
      max: String(range.max),
      unit: range.unit,
    })),
  };
}

function formToPayload(form: AssetFormState): pm.AssetIn {
  const monitored_metrics: Record<string, pm.MetricRange> = {};
  for (const m of form.metrics) {
    if (!m.metric.trim()) continue;
    monitored_metrics[m.metric.trim()] = { min: Number(m.min), max: Number(m.max), unit: m.unit };
  }
  return {
    asset_code: form.asset_code.trim(),
    name: form.name.trim(),
    category: form.category.trim(),
    line_area: form.line_area.trim(),
    criticality: form.criticality ? form.criticality : undefined,
    monitored_metrics,
    // service_intervals deliberately omitted — set from the Maintenance
    // History log now, not here, so saving the asset's other fields never
    // wipes out intervals configured from a maintenance entry.
    install_date: form.install_date || null,
  };
}

function metricsSummary(asset: pm.Asset): string {
  const entries = Object.entries(asset.monitored_metrics);
  if (entries.length === 0) return "";
  return entries.map(([metric, r]) => `${metric} ${r.min} to ${r.max}${r.unit}`).join(", ");
}

function maintenanceTypeLabel(type: string): string {
  return type === "preventive" ? "Scheduled Maintenance" : type === "corrective" ? "Breakdown Repair" : type;
}

function intervalSummary(asset: pm.Asset): string {
  const entries = Object.entries(asset.service_intervals);
  if (entries.length === 0) return "";
  return entries.map(([task, cfg]) => `${cfg.interval_hours}h ${task}`).join(", ");
}

const formGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "16px 16px",
};

function AssetForm({
  initial,
  editing,
  lines,
  onCancel,
  onSave,
}: {
  initial: AssetFormState;
  /** Adjusts the Normal range subtext — adding a brand-new asset vs.
   * editing one that may already have readings coming in against it. */
  editing?: boolean;
  /** Production's configured lines — the Line / area field picks from these
   * instead of free text, so an asset's line always matches a real,
   * currently-configured production line rather than a typo-prone label. */
  lines: ProductionLine[];
  onCancel: () => void;
  onSave: (form: AssetFormState) => Promise<void>;
}) {
  const [form, setForm] = useState<AssetFormState>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // New-asset install date starts prefilled to today as a suggestion, not a
  // confirmed value — render it like hint text until the user actually
  // touches the field, then it reads as a normal, deliberately-chosen date.
  const [installDateTouched, setInstallDateTouched] = useState(false);

  async function handleSave() {
    setError(null);

    // Same "at least one normal range" rule onboarding's quick-add form
    // enforces — without it, an asset can be saved here with no monitored
    // metrics at all, which the recommendation engine can never alert on.
    const filledMetrics = form.metrics.filter((m) => m.metric.trim() || m.min.trim() || m.max.trim() || m.unit.trim());
    if (filledMetrics.length === 0) {
      setError("Add a normal range for this asset — a metric with a min and max — so Plantwise can tell you when it's running outside it.");
      return;
    }
    for (const m of filledMetrics) {
      if (!m.metric.trim() || m.min.trim() === "" || m.max.trim() === "") {
        setError("Each normal range needs a metric name, a min, and a max.");
        return;
      }
      const min = Number(m.min);
      const max = Number(m.max);
      if (Number.isNaN(min) || Number.isNaN(max) || min >= max) {
        setError(`"${m.metric.trim()}"'s min must be a number less than its max.`);
        return;
      }
    }

    setSaving(true);
    try {
      await onSave(form);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Edit mode only: the Save button reads "Update" once something in the
  // form actually differs from the asset's current saved values — before
  // any change, there's nothing to update yet.
  const dirty = editing && JSON.stringify(form) !== JSON.stringify(initial);

  return (
    <div style={{ background: "var(--color-neutral-100)", borderRadius: "var(--radius-lg)", padding: "16px 16px 12px", marginBottom: 16 }}>
      <div style={formGridStyle}>
        <QuickField label="Asset code">
          <input className="input" value={form.asset_code} onChange={(e) => setForm({ ...form, asset_code: e.target.value })} />
        </QuickField>
        <QuickField label="Name">
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </QuickField>
        <QuickField label="Category">
          <input className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
        </QuickField>
        <QuickField label="Line / area">
          <Select
            value={form.line_area}
            onChange={(e) => setForm({ ...form, line_area: e.target.value })}
            options={lines.map((l) => ({ value: l.name, label: l.name }))}
            placeholder={lines.length === 0 ? "No lines configured — add one on Production" : "Select line"}
            disabled={lines.length === 0}
          />
        </QuickField>
        <QuickField label="Criticality">
          <Select
            value={form.criticality}
            onChange={(e) => setForm({ ...form, criticality: e.target.value as AssetFormState["criticality"] })}
            placeholder="Select criticality"
            options={[
              { value: "low", label: "Low" },
              { value: "med", label: "Medium" },
              { value: "high", label: "High" },
            ]}
          />
        </QuickField>
        <QuickField label="Install date">
          {/* Value is already prefilled to today (see makeEmptyForm) so it's
              correct even if the user never touches this field — but showing
              that guessed date as plain text reads as a confirmed fact. Until
              the user actually interacts with the field, mask the native
              input's text and overlay a real "Install date" hint instead, the
              same way a placeholder would read on an empty field. */}
          <div style={{ position: "relative" }}>
            <input
              className="input"
              type="date"
              value={form.install_date}
              onChange={(e) => {
                setForm({ ...form, install_date: e.target.value });
                setInstallDateTouched(true);
              }}
              onFocus={() => setInstallDateTouched(true)}
              style={!editing && !installDateTouched ? { color: "transparent" } : undefined}
            />
            {!editing && !installDateTouched && (
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
                Install date
              </div>
            )}
          </div>
        </QuickField>
      </div>

      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Normal range</div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginBottom: 10, lineHeight: 1.4 }}>
          {editing
            ? "The current safe range for each metric this asset is monitored on. Add, remove, or change one right here."
            : "The safe range for each metric you want this asset monitored on. You can add ranges for more metrics, or fix one later by editing this asset."}
        </div>
        {form.metrics.map((m, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr auto", gap: 8, marginBottom: 8, alignItems: "center" }}>
            <input
              className="input"
              placeholder="metric name (e.g. vibration)"
              value={m.metric}
              onChange={(e) => {
                const metrics = [...form.metrics];
                metrics[i] = { ...metrics[i], metric: e.target.value };
                setForm({ ...form, metrics });
              }}
            />
            <input
              className="input"
              placeholder="min"
              value={m.min}
              onChange={(e) => {
                const metrics = [...form.metrics];
                metrics[i] = { ...metrics[i], min: e.target.value };
                setForm({ ...form, metrics });
              }}
            />
            <input
              className="input"
              placeholder="max"
              value={m.max}
              onChange={(e) => {
                const metrics = [...form.metrics];
                metrics[i] = { ...metrics[i], max: e.target.value };
                setForm({ ...form, metrics });
              }}
            />
            <input
              className="input"
              placeholder="unit"
              value={m.unit}
              onChange={(e) => {
                const metrics = [...form.metrics];
                metrics[i] = { ...metrics[i], unit: e.target.value };
                setForm({ ...form, metrics });
              }}
            />
            <button
              type="button"
              onClick={() => setForm({ ...form, metrics: form.metrics.filter((_, idx) => idx !== i) })}
              className="btn-icon btn-icon--delete"
              style={{ width: 42, height: 42 }}
              aria-label="Remove metric"
              title="Remove metric"
            >
              <X size={14} strokeWidth={2} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setForm({ ...form, metrics: [...form.metrics, { metric: "", min: "", max: "", unit: "" }] })}
          className="btn-secondary"
        >
          + Add Range
        </button>
      </div>

      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 12 }}>{error}</div>}

      <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button onClick={onCancel} className="btn-secondary">
          Cancel
        </button>
        <button className="btn-primary" style={{ minWidth: 160 }} onClick={handleSave} disabled={saving}>
          {editing ? (saving ? "Saving..." : dirty ? "Update" : "Save") : saving ? "Adding..." : "Add Asset"}
        </button>
      </div>
    </div>
  );
}

function AssetDrillDown({ asset, onClose }: { asset: pm.Asset; onClose: () => void }) {
  const metrics = Object.keys(asset.monitored_metrics);
  const [metric, setMetric] = useState(metrics[0] ?? "");
  const [series, setSeries] = useState<pm.ReadingsSeries | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!metric) return;
    setLoading(true);
    pm.getAssetReadings(asset.id, metric, 30)
      .then(setSeries)
      .finally(() => setLoading(false));
  }, [asset.id, metric]);

  // v1 is daily-batch (PRD §7) — a gap of more than ~1.5 days between two
  // readings means a refresh was missed, not a smooth continuous trend.
  // Insert an explicit null point so the line actually breaks there instead
  // of Recharts drawing a straight (and misleading) line across the gap.
  const GAP_THRESHOLD_MS = 36 * 60 * 60 * 1000;

  const chartData = useMemo(() => {
    const readings = series?.readings ?? [];
    const points: Array<{ timestamp: string; value: number | null }> = [];
    let prevTs: number | null = null;
    for (const r of readings) {
      const ts = new Date(r.timestamp).getTime();
      if (prevTs !== null && ts - prevTs > GAP_THRESHOLD_MS) {
        points.push({ timestamp: new Date((prevTs + ts) / 2).toLocaleDateString(), value: null });
      }
      points.push({ timestamp: new Date(ts).toLocaleDateString(), value: r.value });
      prevTs = ts;
    }
    return points;
  }, [series]);

  return (
    <DrillDownModal title={`${asset.name}: trend`} onClose={onClose}>
      {metrics.length > 1 && (
        <div style={{ marginBottom: 12 }}>
          <Select value={metric} onChange={(e) => setMetric(e.target.value)} options={metrics.map((m) => ({ value: m, label: m }))} />
        </div>
      )}
      {!metric && <EmptyState title="No monitored metrics" message="This asset has no configured metrics yet." />}
      {metric && loading && <Skeleton rows={1} height={280} />}
      {metric && !loading && chartData.length === 0 && (
        <EmptyState title="No readings yet" message={`No ${metric} readings in the last 30 days.`} />
      )}
      {metric && !loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
            <Tooltip />
            {series?.min != null && <ReferenceLine y={series.min} stroke="var(--color-warning-500)" strokeDasharray="4 4" label="min" />}
            {series?.max != null && <ReferenceLine y={series.max} stroke="var(--color-error-500)" strokeDasharray="4 4" label="max" />}
            <Line type="monotone" dataKey="value" stroke="var(--color-primary-600)" dot={{ r: 3 }} connectNulls={false} name={`${metric} (${series?.unit ?? ""})`} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </DrillDownModal>
  );
}

/** Matches the wireframe's recommendation-list row: colored left bar by
 * urgency, id + asset + urgency badge + status, issue title, evidence line. */
function RecommendationRow({
  rec,
  assetName,
  onRefresh,
  highlighted,
}: {
  rec: pm.Recommendation;
  assetName: string;
  onRefresh: () => void;
  highlighted?: boolean;
}) {
  const [picking, setPicking] = useState(false);
  const [history, setHistory] = useState<pm.MaintenanceHistoryRecord[]>([]);
  const [selectedMh, setSelectedMh] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const barColor = URGENCY_BAR[rec.urgency];

  async function openActionPicker() {
    setBusy(true);
    try {
      const h = await pm.getAssetMaintenanceHistory(rec.asset_id);
      setHistory(h);
      setSelectedMh(h[0]?.id ?? null);
      setPicking(true);
    } finally {
      setBusy(false);
    }
  }

  async function confirmAction() {
    if (selectedMh == null) return;
    setBusy(true);
    try {
      await pm.actionRecommendation(rec.id, selectedMh);
      setPicking(false);
      onRefresh();
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge() {
    setBusy(true);
    try {
      await pm.acknowledgeRecommendation(rec.id);
      onRefresh();
    } finally {
      setBusy(false);
    }
  }

  async function dismiss() {
    setBusy(true);
    try {
      await pm.dismissRecommendation(rec.id);
      onRefresh();
    } finally {
      setBusy(false);
    }
  }

  const showActions = rec.status !== "actioned" && rec.status !== "dismissed";

  return (
    <div
      id={`recommendation-${rec.id}`}
      style={{
        display: "flex",
        alignItems: "stretch",
        background: highlighted ? "var(--color-accent-50)" : "var(--color-surface-default)",
        border: highlighted ? "1px solid var(--color-accent-600)" : "1px solid var(--color-border-default)",
        borderRadius: "var(--radius-xl)",
        overflow: "hidden",
        marginBottom: 10,
        boxShadow: "var(--shadow-xs)",
      }}
    >
      <div style={{ width: 4, background: barColor, flex: "none" }} />
      <div style={{ flex: 1, padding: "12px 16px", minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{assetName}</span>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3, color: URGENCY_TEXT[rec.urgency] }}>
            {URGENCY_LABEL[rec.urgency]}
          </span>
          <span style={{ marginLeft: "auto", fontSize: 11.5, fontWeight: 600, color: "var(--color-text-tertiary)", textTransform: "capitalize", whiteSpace: "nowrap" }}>
            {rec.status}
          </span>
        </div>
        <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 3, lineHeight: 1.3 }}>{rec.issue}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", lineHeight: 1.4, marginBottom: 8 }}>{rec.evidence}</div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              fontSize: 11.5,
              border: "1px solid var(--color-border-default)",
              borderRadius: "var(--radius-full)",
              padding: "3px 10px 3px 4px",
              color: "var(--color-text-tertiary)",
            }}
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: 0.3,
                background: "var(--color-neutral-100)",
                color: "var(--color-text-tertiary)",
                borderRadius: "var(--radius-full)",
                padding: "2px 7px",
              }}
            >
              Recommended
            </span>
            {rec.recommended_action}
          </span>

          <RoleGuard allow={["admin", "operator"]}>
            {showActions && !picking && (
              <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
                {rec.status === "open" && (
                  <button
                    onClick={acknowledge}
                    disabled={busy}
                    className="btn-secondary"
                    style={{ fontSize: 11.5, padding: "6px 12px", borderColor: "var(--color-info-200)", background: "var(--color-info-50)", color: "var(--color-info-700)" }}
                  >
                    Acknowledge
                  </button>
                )}
                <button
                  onClick={openActionPicker}
                  disabled={busy}
                  className="btn-secondary"
                  style={{ fontSize: 11.5, padding: "6px 12px", borderColor: "var(--color-success-200)", background: "var(--color-success-50)", color: "var(--color-success-700)" }}
                >
                  Mark Actioned
                </button>
                <button onClick={dismiss} disabled={busy} className="btn-danger" style={{ fontSize: 11.5, padding: "6px 12px" }}>
                  Dismiss
                </button>
              </div>
            )}
          </RoleGuard>
        </div>

        <RoleGuard allow={["admin", "operator"]}>
          {picking && (
            <div style={{ marginTop: 10 }}>
              {history.length === 0 ? (
                <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
                  No maintenance history for this asset yet. Upload one (CSV or Excel) first.
                </span>
              ) : (
                <Select
                  style={{ width: "100%" }}
                  value={selectedMh ?? ""}
                  onChange={(e) => setSelectedMh(Number(e.target.value))}
                  options={history.map((h) => ({
                    value: h.id,
                    label: `${h.date} · ${maintenanceTypeLabel(h.type)} · ${h.description || "(no description)"}`,
                  }))}
                />
              )}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
                <button onClick={() => setPicking(false)} className="btn-secondary">
                  Cancel
                </button>
                {history.length > 0 && (
                  <button className="btn-primary" onClick={confirmAction} disabled={busy}>
                    Link & Action
                  </button>
                )}
              </div>
            </div>
          )}
        </RoleGuard>
      </div>
    </div>
  );
}

/** A row in the "logged this session" list below a quick-log form — same
 * bordered-card treatment and Edit/Delete icons (RowActions) as every
 * config table in the app (asset registry, lines, items, ...), so this
 * reads as the same kind of list, not a one-off. `editing` swaps the
 * display row for the caller's inline edit form. */
function LoggedRow({
  display,
  editing,
  onEdit,
  onDelete,
}: {
  display: React.ReactNode;
  editing: React.ReactNode | null;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        fontSize: 12.5,
        color: "var(--color-text-secondary)",
        background: "var(--color-surface-default)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: "var(--radius-md)",
        padding: "8px 10px",
      }}
    >
      {editing ?? (
        <>
          <span>{display}</span>
          <RowActions onEdit={onEdit} onDelete={onDelete} />
        </>
      )}
    </div>
  );
}

/** One asset's reading logged for right now — the "quick daily form"
 * alternative to building a sensor-readings CSV for a single row (PRD §4.9). */
export function QuickReadingLog({ assets, onLogged }: { assets: pm.Asset[]; onLogged: () => void }) {
  const [assetId, setAssetId] = useState<number | "">("");
  const [metric, setMetric] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [logged, setLogged] = useState<{ id: number; assetId: number; assetLabel: string; metric: string; value: number; unit: string }[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editUnit, setEditUnit] = useState("");
  const lastLogged = useRef<pm.Reading | null>(null);

  const selectedAsset = assets.find((a) => a.id === assetId);
  const knownMetrics = Object.keys(selectedAsset?.monitored_metrics ?? {});

  useEffect(() => {
    // Metric choices come only from the asset's own configured normal
    // ranges — there's no free-text "Other" escape hatch here, so leave
    // Metric unselected until an asset (and its metrics list) is known.
    setMetric(Object.keys(selectedAsset?.monitored_metrics ?? {})[0] ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  useEffect(() => {
    if (selectedAsset) {
      setUnit(selectedAsset.monitored_metrics[metric]?.unit ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metric]);

  return (
    <div className="pm-quick-reading">
      <QuickLogForm
        submitLabel="Log Reading"
        syncEntity="sensor_readings"
        hideSuccessMessage
        disabled={!assetId || !metric || value === ""}
        onSubmit={async () => {
          if (!assetId || !metric || value === "") return;
          lastLogged.current = await pm.quickLogReading(assetId, { metric, value: Number(value), unit });
        }}
        onSubmitted={() => {
          const reading = lastLogged.current;
          if (reading?.id != null && assetId) {
            setLogged((prev) => [
              { id: reading.id!, assetId, assetLabel: selectedAsset?.name ?? "Asset", metric, value: reading.value, unit: reading.unit },
              ...prev,
            ]);
          }
          setValue("");
          onLogged();
        }}
      >
        <QuickField label="Asset">
          <Select
            value={assetId}
            onChange={(e) => setAssetId(Number(e.target.value))}
            options={assets.map((a) => ({ value: a.id, label: a.name }))}
            placeholder="Select asset"
          />
        </QuickField>
        <QuickField label="Metric">
          <Select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            options={knownMetrics.map((m) => ({ value: m, label: m }))}
            placeholder={selectedAsset ? "Select metric" : "Metric"}
            disabled={!selectedAsset}
          />
        </QuickField>
        <QuickField label="Value">
          <input className="input" type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} />
        </QuickField>
        <QuickField label="Unit">
          {/* Unit comes from the asset's own configured normal range for
              this metric, not a free-typed value — same "edit the asset to
              change it" rule as the metric choice itself. */}
          <input className="input" value={unit} disabled={!!metric} placeholder="mm/s" />
        </QuickField>
      </QuickLogForm>
      {logged.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
          {logged.map((entry) => (
            <LoggedRow
              key={entry.id}
              display={`${entry.assetLabel} — ${entry.metric}: ${entry.value}${entry.unit ? ` ${entry.unit}` : ""}`}
              editing={
                editingId === entry.id ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flex: 1 }}>
                    <input className="input" style={{ height: 32 }} type="number" step="any" value={editValue} onChange={(e) => setEditValue(e.target.value)} aria-label="Value" />
                    <input className="input" style={{ height: 32 }} value={editUnit} onChange={(e) => setEditUnit(e.target.value)} placeholder="Unit" aria-label="Unit" />
                    <button
                      className="btn-primary"
                      style={{ height: 32, padding: "0 12px", fontSize: 12.5 }}
                      onClick={async () => {
                        const updated = await pm.updateReading(entry.assetId, entry.id, { value: Number(editValue), unit: editUnit });
                        setLogged((prev) => prev.map((e) => (e.id === entry.id ? { ...e, value: updated.value, unit: updated.unit } : e)));
                        setEditingId(null);
                      }}
                    >
                      Save
                    </button>
                    <button type="button" className="btn-ghost" style={{ height: 32, fontSize: 12.5 }} onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </div>
                ) : null
              }
              onEdit={() => {
                setEditingId(entry.id);
                setEditValue(String(entry.value));
                setEditUnit(entry.unit);
              }}
              onDelete={async () => {
                await pm.deleteReading(entry.assetId, entry.id);
                setLogged((prev) => prev.filter((e) => e.id !== entry.id));
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const SERVICE_INTERVAL_OPTIONS = [
  { value: "250", label: "Every 250 hours" },
  { value: "500", label: "Every 500 hours" },
  { value: "1000", label: "Every 1000 hours" },
  { value: "2000", label: "Every 2000 hours" },
  { value: "5000", label: "Every 5000 hours" },
];

export function QuickMaintenanceLog({ assets, onLogged }: { assets: pm.Asset[]; onLogged: () => void }) {
  const [assetId, setAssetId] = useState<number | "">("");
  const [type, setType] = useState<"preventive" | "corrective">("preventive");
  const [description, setDescription] = useState("");
  const [downtimeHours, setDowntimeHours] = useState("");
  const [partsReplaced, setPartsReplaced] = useState("");
  // Sets the asset's recurring service interval for this task at the same
  // time you log that you did it — replaces the old separate "Service
  // intervals" section on the Asset Registry form.
  const [serviceIntervalHours, setServiceIntervalHours] = useState("");
  const [logged, setLogged] = useState<
    { id: number; assetId: number; assetLabel: string; type: "preventive" | "corrective"; description: string }[]
  >([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editType, setEditType] = useState<"preventive" | "corrective">("preventive");
  const [editDescription, setEditDescription] = useState("");
  const lastLogged = useRef<pm.MaintenanceHistoryRecord | null>(null);

  useEffect(() => {
    // A recurring interval ("do this every N hours") only makes sense for a
    // scheduled task — a breakdown repair is by definition unplanned, so it
    // has no cadence to set. Clear it on switch so a leftover value from
    // Scheduled maintenance can't silently apply to a Breakdown repair entry.
    if (type === "corrective") setServiceIntervalHours("");
  }, [type]);

  return (
    <div className="pm-quick-reading">
      <QuickLogForm
        submitLabel="Log Service"
        syncEntity="maintenance_history"
        hideSuccessMessage
        disabled={!assetId || !type}
        onSubmit={async () => {
          if (!assetId) return;
          lastLogged.current = await pm.quickLogMaintenance(assetId, {
            type,
            description,
            downtime_hours: downtimeHours ? Number(downtimeHours) : 0,
            parts_replaced: partsReplaced || null,
          });
          if (serviceIntervalHours) {
            const asset = assets.find((a) => a.id === assetId);
            const taskKey = description.trim() || "service";
            await pm.updateAsset(assetId, {
              service_intervals: { ...(asset?.service_intervals ?? {}), [taskKey]: { interval_hours: Number(serviceIntervalHours) } },
            });
          }
        }}
        onSubmitted={() => {
          const record = lastLogged.current;
          if (record && assetId) {
            setLogged((prev) => [
              { id: record.id, assetId, assetLabel: assets.find((a) => a.id === assetId)?.name ?? "Asset", type: record.type, description: record.description },
              ...prev,
            ]);
          }
          setDescription("");
          setDowntimeHours("");
          setPartsReplaced("");
          setServiceIntervalHours("");
          onLogged();
        }}
      >
        <QuickField label="Asset">
          <Select
            value={assetId}
            onChange={(e) => setAssetId(Number(e.target.value))}
            options={assets.map((a) => ({ value: a.id, label: a.name }))}
            placeholder="Select asset"
          />
        </QuickField>
        <QuickField label="Type">
          <Select
            value={type}
            onChange={(e) => setType(e.target.value as "preventive" | "corrective")}
            options={[
              { value: "preventive", label: "Scheduled Maintenance" },
              { value: "corrective", label: "Breakdown Repair" },
            ]}
          />
        </QuickField>
        <QuickField label="Description">
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (e.g. Motor was overheating, replaced worn drive belt)"
          />
        </QuickField>
        <QuickField label="Downtime hours">
          <input className="input" type="number" step="any" value={downtimeHours} onChange={(e) => setDowntimeHours(e.target.value)} />
        </QuickField>
        <QuickField label="Parts replaced">
          <input
            className="input"
            value={partsReplaced}
            onChange={(e) => setPartsReplaced(e.target.value)}
            placeholder="Parts replaced (e.g. bearing, seal kit)"
          />
        </QuickField>
        {type === "preventive" && (
          <QuickField label="Service interval">
            <Select
              value={serviceIntervalHours}
              onChange={(e) => setServiceIntervalHours(e.target.value)}
              options={SERVICE_INTERVAL_OPTIONS}
              placeholder="Repeat every (optional)"
            />
          </QuickField>
        )}
      </QuickLogForm>
      {logged.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
          {logged.map((entry) => (
            <LoggedRow
              key={entry.id}
              display={`${entry.assetLabel} — ${entry.type === "preventive" ? "Scheduled Maintenance" : "Breakdown Repair"}${entry.description ? `: ${entry.description}` : ""}`}
              editing={
                editingId === entry.id ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flex: 1 }}>
                    <Select
                      style={{ height: 32, width: 170 }}
                      value={editType}
                      onChange={(e) => setEditType(e.target.value as "preventive" | "corrective")}
                      options={[
                        { value: "preventive", label: "Scheduled Maintenance" },
                        { value: "corrective", label: "Breakdown Repair" },
                      ]}
                    />
                    <input className="input" style={{ height: 32, flex: 1 }} value={editDescription} onChange={(e) => setEditDescription(e.target.value)} aria-label="Description" />
                    <button
                      className="btn-primary"
                      style={{ height: 32, padding: "0 12px", fontSize: 12.5 }}
                      onClick={async () => {
                        const updated = await pm.updateMaintenanceRecord(entry.assetId, entry.id, { type: editType, description: editDescription });
                        setLogged((prev) => prev.map((e) => (e.id === entry.id ? { ...e, type: updated.type, description: updated.description } : e)));
                        setEditingId(null);
                      }}
                    >
                      Save
                    </button>
                    <button type="button" className="btn-ghost" style={{ height: 32, fontSize: 12.5 }} onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </div>
                ) : null
              }
              onEdit={() => {
                setEditingId(entry.id);
                setEditType(entry.type);
                setEditDescription(entry.description);
              }}
              onDelete={async () => {
                await pm.deleteMaintenanceRecord(entry.assetId, entry.id);
                setLogged((prev) => prev.filter((e) => e.id !== entry.id));
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

type Tab = "recommendations" | "registry" | "readings" | "history";

export default function PredictiveMaintenancePage() {
  const [assets, setAssets] = useState<pm.Asset[]>([]);
  const [recommendations, setRecommendations] = useState<pm.Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // For AssetForm's Line / area dropdown — Production's own lines, not
  // scoped to statusFilter/refetchAll since they don't change with it.
  const [productionLines, setProductionLines] = useState<ProductionLine[]>([]);
  useEffect(() => {
    getLines().then(setProductionLines).catch(() => undefined);
  }, []);

  const [editingAsset, setEditingAsset] = useState<pm.Asset | null>(null);
  // The edit form renders below the assets table, out of view when the list
  // is long — without this, tapping Edit updates state but the user stays
  // scrolled wherever they already were and never sees the form appear.
  useEffect(() => {
    if (editingAsset) {
      document.getElementById("pm-edit-asset")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [editingAsset]);
  // Bumped after every manual "add asset" save (or its Cancel) to remount
  // the Manual Entry form with a fresh, empty AssetForm instead of leaving
  // the just-submitted values sitting in the persistent tab.
  const [manualFormKey, setManualFormKey] = useState(0);
  const [drilldownAsset, setDrilldownAsset] = useState<pm.Asset | null>(null);
  const [searchParams] = useSearchParams();
  // Alert emails deep-link to a specific recommendation (?recommendation_id=N,
  // see notifications/service.py dashboard_link) — start on "All" so it's
  // visible regardless of its current status, then scroll/highlight it below.
  const highlightRecId = searchParams.get("recommendation_id");
  const [statusFilter, setStatusFilter] = useState<string>(highlightRecId ? "" : "open");
  // The dashboard's Issues chart deep-links here with ?urgency=high so
  // clicking a bar/legend there lands straight on the matching filter.
  const urgencyParam = searchParams.get("urgency");
  const [urgencyFilter, setUrgencyFilter] = useState<pm.Urgency | "">(
    urgencyParam === "high" || urgencyParam === "med" || urgencyParam === "low" ? urgencyParam : ""
  );
  const [tab, setTab] = useState<Tab>("recommendations");
  const [freshness, setFreshness] = useState<{ last_updated_at: string | null; is_stale: boolean; expected_cadence_hours: number | null } | null>(null);
  const [stats, setStats] = useState<pm.RecommendationStats | null>(null);

  // Mirrors ConfigImportTabs' own "is the Database Import tab even offered"
  // check — once true, mentioning "or a database" in the Add Assets copy
  // would describe an option that isn't actually there anymore.
  const assetsActiveSync = useActiveSyncSchedule("assets");
  const isDbConnected = useIsDbConnected();
  // isDbConnected === false, not just falsy — same reasoning as
  // ConfigImportTabs' dbAvailable: while it's still null (loading), that
  // must not be read as "no connection," or the "or connect a database"
  // wording flashes on then off once the real answer arrives.
  const dbStillAnOption = !assetsActiveSync && isDbConnected === false;
  const addAssetsSubtitle = dbStillAnOption
    ? "Register a new asset with its normal ranges, or upload files to import multiple assets at once, or connect a database."
    : "Register a new asset with its normal ranges, or upload files to import multiple assets at once.";

  async function refetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [a, r] = await Promise.all([pm.listAssets(), pm.listRecommendations({ status: statusFilter || undefined })]);
      setAssets(a);
      setRecommendations(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load predictive maintenance data");
    } finally {
      setLoading(false);
    }
    // Outcomes (PRD §5.7 "recommendation outcomes... feeds the precision
    // metric") aren't scoped to the status filter — always the full picture.
    pm.getRecommendationStats().then(setStats).catch(() => undefined);
  }

  useEffect(() => {
    refetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  useEffect(() => {
    if (!highlightRecId || recommendations.length === 0) return;
    setTab("recommendations");
    document.getElementById(`recommendation-${highlightRecId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightRecId, recommendations]);

  useEffect(() => {
    getDashboardSummary()
      .then((summaries) => {
        const s = summaries.find((x) => x.module === "predictive_maintenance");
        if (s) setFreshness({ last_updated_at: s.last_updated_at, is_stale: s.is_stale, expected_cadence_hours: s.expected_cadence_hours });
      })
      .catch(() => undefined);
  }, []);

  const assetNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const a of assets) map.set(a.id, a.name);
    return map;
  }, [assets]);

  const openRecommendations = useMemo(() => recommendations.filter((r) => r.status === "open"), [recommendations]);
  const sortedRecommendations = useMemo(
    () =>
      recommendations
        .filter((r) => !urgencyFilter || r.urgency === urgencyFilter)
        .sort((a, b) => URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency]),
    [recommendations, urgencyFilter]
  );

  async function handleSaveAsset(form: AssetFormState) {
    const payload = formToPayload(form);
    if (editingAsset) {
      await pm.updateAsset(editingAsset.id, payload);
    } else {
      await pm.createAsset(payload);
    }
    setEditingAsset(null);
    await refetchAll();
  }

  /** Manual Entry tab in the Assets config area — a plain create, kept
   * separate from handleSaveAsset (which also handles editing an existing
   * asset from the table) so the form can be remounted empty afterward
   * instead of closing/disappearing. */
  async function handleManualAddAsset(form: AssetFormState) {
    const payload = formToPayload(form);
    await pm.createAsset(payload);
    await refetchAll();
    setManualFormKey((k) => k + 1);
  }

  async function handleDeleteAsset(asset: pm.Asset) {
    if (!confirm(`Delete asset ${asset.name}?`)) return;
    try {
      await pm.deleteAsset(asset.id);
      await refetchAll();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: "recommendations", label: "Recommendations" },
    { key: "registry", label: "Asset Registry" },
    { key: "readings", label: "Sensor Readings" },
    { key: "history", label: "Maintenance History" },
  ];

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="maintenance" />}
        title="Predictive Maintenance"
        subtitle="Rule-based alerts from readings and service history"
        actions={
          <>
            {/* Reflects when readings/history data was last ingested for the
                detection engine's daily refresh — not whether assets exist,
                so it's only shown where that's relevant (not on the Asset
                Registry tab, where "No data yet" would misleadingly read as
                "no assets configured"). */}
            {freshness && tab !== "registry" && (
              <FreshnessBadge
                lastUpdatedAt={freshness.last_updated_at}
                isStale={freshness.is_stale}
                expectedCadenceHours={freshness.expected_cadence_hours}
              />
            )}
            {/* Redundant on the Recommendations tab itself — the list below
                already shows exactly this. Kept as a jump-to shortcut from
                the other three tabs. */}
            {tab !== "recommendations" && (
              <button
                className="btn-secondary"
                onClick={() => {
                  setStatusFilter("open");
                  setTab("recommendations");
                }}
                disabled={openRecommendations.length === 0}
              >
                {openRecommendations.length === 0
                  ? "No Open Recommendations"
                  : `View ${openRecommendations.length} Recommendation${openRecommendations.length === 1 ? "" : "s"}`}
              </button>
            )}
            {/* Redundant on the Sensor Readings tab itself — you're already
                there. Kept as a jump-to shortcut from the other tabs. */}
            {tab !== "readings" && (
              <RoleGuard allow={["admin", "operator"]}>
                <button className="btn-primary" onClick={() => setTab("readings")}>
                  Upload Readings Data
                </button>
              </RoleGuard>
            )}
          </>
        }
      />

      {error && <div style={{ color: "var(--color-error-600)", marginBottom: 12 }}>{error}</div>}

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as Tab)} />

      {tab === "registry" && (
        <>
          <RoleGuard allow={["operator", "viewer"]}>
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Registry editing is Admin-only</span>
          </RoleGuard>

          {loading ? (
            <Skeleton rows={3} />
          ) : assets.length === 0 ? (
            <EmptyState title="No assets yet" message="Add an asset below to start monitoring it." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Code</Th>
                  <Th>Asset</Th>
                  <Th>Category</Th>
                  <Th>Line</Th>
                  <Th>Criticality</Th>
                  <Th>Normal range</Th>
                  <Th>Interval</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </THead>
              <TBody>
                {assets.map((asset) => (
                  <Tr key={asset.id} onClick={() => setDrilldownAsset(asset)}>
                    <Td>{asset.asset_code}</Td>
                    <Td>
                      <span style={{ fontWeight: 600 }}>{asset.name}</span>
                    </Td>
                    <Td>{asset.category}</Td>
                    <Td>{asset.line_area}</Td>
                    <Td>
                      <Badge variant={urgencyVariant(asset.criticality)}>{CRITICALITY_LABEL[asset.criticality]}</Badge>
                    </Td>
                    <Td wrap>{metricsSummary(asset)}</Td>
                    <Td wrap>{intervalSummary(asset)}</Td>
                    <Td align="right">
                      <RoleGuard allow={["admin"]}>
                        <RowActions
                          onEdit={() => setEditingAsset(asset)}
                          onDelete={() => handleDeleteAsset(asset)}
                        />
                      </RoleGuard>
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}

          <RoleGuard allow={["admin"]}>
            {editingAsset && (
              <div id="pm-edit-asset" style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 15, marginBottom: 10 }}>Edit {editingAsset.name}</h3>
                {/* Keyed on the asset id so switching Edit from one asset to
                    another remounts the form with fresh initial values —
                    without this, AssetForm's internal useState(initial) only
                    runs on first mount, so the second asset's form kept
                    showing the first asset's still-loaded field values under
                    the new title. */}
                <AssetForm
                  key={editingAsset.id}
                  initial={assetToForm(editingAsset)}
                  editing
                  lines={productionLines}
                  onCancel={() => setEditingAsset(null)}
                  onSave={handleSaveAsset}
                />
              </div>
            )}
          </RoleGuard>

          <RoleGuard allow={["admin"]}>
            <div style={{ marginTop: 24 }}>
              <FormSection title="Add Assets" subtitle={addAssetsSubtitle} collapsible defaultOpen={false}>
                <ConfigImportTabs
                  manual={
                    <AssetForm
                      key={manualFormKey}
                      initial={makeEmptyForm()}
                      lines={productionLines}
                      onCancel={() => setManualFormKey((k) => k + 1)}
                      onSave={handleManualAddAsset}
                    />
                  }
                  csv={{
                    title: "Import Assets",
                    hideHeading: true,
                    moduleLabel: "Predictive Maintenance",
                    templatePath: pm.ASSET_CSV_PATHS.template,
                    mapPath: pm.ASSET_CSV_PATHS.map,
                    validatePath: pm.ASSET_CSV_PATHS.validate,
                    commitPath: pm.ASSET_CSV_PATHS.commit,
                    onCommitted: refetchAll,
                    syncEntity: "assets",
                    fieldChips: <FieldChips fields={["asset_code", "name", "category", "line_area", "criticality", "install_date"]} />,
                  }}
                  db={{
                    entity: "assets",
                    title: "Assets",
                    moduleLabel: "Predictive Maintenance",
                    onCommitted: refetchAll,
                  }}
                />
              </FormSection>
            </div>
          </RoleGuard>
        </>
      )}

      {tab === "readings" && assets.length > 0 && (
        <RoleGuard allow={["admin", "operator"]}>
          <FormSection title="Sensor Readings" subtitle="Daily or per-shift sensor readings used for threshold and trend detection.">
            <ConfigImportTabs
              manual={<QuickReadingLog assets={assets} onLogged={refetchAll} />}
              csv={{
                title: "Sensor Readings",
                hideHeading: true,
                moduleLabel: "Predictive Maintenance",
                templatePath: pm.READINGS_CSV_PATHS.template,
                mapPath: pm.READINGS_CSV_PATHS.map,
                validatePath: pm.READINGS_CSV_PATHS.validate,
                commitPath: pm.READINGS_CSV_PATHS.commit,
                onCommitted: refetchAll,
                syncEntity: "sensor_readings",
                fieldChips: <FieldChips fields={["asset_id", "timestamp", "metric", "value", "unit"]} />,
              }}
              db={{ entity: "sensor_readings", title: "Sensor Readings", moduleLabel: "Predictive Maintenance", onCommitted: refetchAll }}
            />
          </FormSection>
        </RoleGuard>
      )}

      {tab === "history" && assets.length > 0 && (
        <RoleGuard allow={["admin", "operator"]}>
          <FormSection
            title="Maintenance History"
            subtitle="Record scheduled maintenance and breakdown repairs for your assets."
          >
            <ConfigImportTabs
              manual={<QuickMaintenanceLog assets={assets} onLogged={refetchAll} />}
              csv={{
                title: "Maintenance History",
                hideHeading: true,
                moduleLabel: "Predictive Maintenance",
                templatePath: pm.MAINTENANCE_CSV_PATHS.template,
                mapPath: pm.MAINTENANCE_CSV_PATHS.map,
                validatePath: pm.MAINTENANCE_CSV_PATHS.validate,
                commitPath: pm.MAINTENANCE_CSV_PATHS.commit,
                onCommitted: refetchAll,
                syncEntity: "maintenance_history",
                fieldChips: (
                  <FieldChips fields={["asset_id", "date", "type", "description", "downtime_hours", "parts_replaced", "service_interval_hours"]} />
                ),
              }}
              db={{ entity: "maintenance_history", title: "Maintenance History", moduleLabel: "Predictive Maintenance", onCommitted: refetchAll }}
            />
          </FormSection>
        </RoleGuard>
      )}


      {tab === "recommendations" && (
        <>
          <div
            style={{
              marginBottom: 16,
              background: "var(--color-accent-50)",
              border: "1px solid var(--color-accent-600)",
              borderRadius: "var(--radius-lg)",
              padding: "10px 14px",
              fontSize: 13,
              color: "var(--color-text-primary)",
            }}
          >
            <strong>How this works:</strong> each day, we compare every asset's latest readings against its normal
            ranges and service schedule, and flag any threshold breach, unusual trend, or overdue maintenance.
          </div>

          {stats && stats.total > 0 && (
            <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
              {[
                { label: "Total raised", value: stats.total, filter: "" },
                { label: "Still open", value: stats.by_status.open ?? 0, filter: "open" },
                { label: "Acknowledged", value: stats.by_status.acknowledged ?? 0, filter: "acknowledged" },
                { label: "Acted on", value: stats.by_status.actioned ?? 0, filter: "actioned" },
                { label: "Dismissed", value: stats.by_status.dismissed ?? 0, filter: "dismissed" },
              ].map((tile) => {
                const active = statusFilter === tile.filter;
                return (
                  <button
                    key={tile.label}
                    type="button"
                    onClick={() => {
                      setStatusFilter(tile.filter);
                      document.getElementById("pm-recommendations")?.scrollIntoView({ behavior: "smooth" });
                    }}
                    className="surface"
                    style={{
                      padding: "12px 16px",
                      flex: "1 1 130px",
                      textAlign: "left",
                      cursor: "pointer",
                      font: "inherit",
                      // Uniform gold "selected" treatment (same formula as the
                      // app's segmented toggles) regardless of which tile is
                      // active — a consistent selector, not a per-metric tint.
                      border: active ? "1.5px solid var(--color-accent-400)" : "1px solid var(--color-border-subtle)",
                      background: active ? "var(--color-accent-100)" : "var(--color-surface-default)",
                    }}
                  >
                    <div style={{ fontSize: 11.5, fontWeight: 600, color: active ? "var(--color-accent-900)" : "var(--color-text-secondary)", marginBottom: 4 }}>
                      {tile.label}
                    </div>
                    <div className="num" style={{ fontSize: 22, fontWeight: 800, color: active ? "var(--color-accent-900)" : "var(--color-text-primary)" }}>
                      {tile.value}
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          <div id="pm-recommendations" style={{ scrollMarginTop: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
              <Select
                style={{ width: 130 }}
                value={urgencyFilter}
                onChange={(e) => setUrgencyFilter(e.target.value as pm.Urgency | "")}
                options={[
                  { value: "", label: "All criticality" },
                  { value: "high", label: "High" },
                  { value: "med", label: "Medium" },
                  { value: "low", label: "Low" },
                ]}
              />
            </div>
            {loading ? (
              <Skeleton rows={3} height={80} />
            ) : sortedRecommendations.length === 0 ? (
              <EmptyState title="No recommendations" message="Nothing flagged for this filter." />
            ) : (
              sortedRecommendations.map((rec) => (
                <RecommendationRow
                  key={rec.id}
                  rec={rec}
                  assetName={assetNameById.get(rec.asset_id) ?? `Asset #${rec.asset_id}`}
                  onRefresh={refetchAll}
                  highlighted={String(rec.id) === highlightRecId}
                />
              ))
            )}
          </div>
        </>
      )}

      {drilldownAsset && <AssetDrillDown asset={drilldownAsset} onClose={() => setDrilldownAsset(null)} />}
    </div>
  );
}

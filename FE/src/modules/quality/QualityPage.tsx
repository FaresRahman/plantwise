import React, { useEffect, useMemo, useState } from "react";
import { Check, Lightbulb, TrendingUp } from "lucide-react";
import { CartesianGrid, Line as RechartsLine, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { getDashboardSummary } from "../../api/dashboard";
import * as productionApi from "../../api/production";
import type { Line } from "../../api/production";
import {
  Characteristic,
  CharacteristicIn,
  CharacteristicTrend,
  createCharacteristic,
  createHold,
  deleteCharacteristic,
  getCharacteristicMeasurements,
  getCharacteristicTrend,
  getCharacteristics,
  getHolds,
  CHARACTERISTIC_CSV_PATHS,
  INSPECTION_RECORDS_CSV_PATHS,
  Measurement,
  quickLogInspection,
  QualityHold,
  QualityHoldIn,
  releaseHold,
  updateCharacteristic,
} from "../../api/quality";
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
import { LegendDot, PanelHeader } from "../dashboard/AnalyticsPanels";

/** Tints CharacteristicForm as an inset zone within its surrounding card
 * (the Edit block or the Add Characteristics section's Manual Entry tab) —
 * same treatment as Production's LineForm, Predictive Maintenance's
 * AssetForm, and Inventory's ItemForm. */
const quickAddCardStyle: React.CSSProperties = { background: "var(--color-neutral-100)", borderRadius: "var(--radius-lg)", padding: 16 };

/** Measured values against tolerance, over time, per characteristic — lives
 * on the Dashboard (see DashboardPage.tsx), not here, so a look at "how's
 * quality doing" doesn't require drilling into this page first. Exported
 * from here rather than duplicated since it's Quality's own chart. */
export function QualityMeasurementsPanel({ characteristics }: { characteristics: Characteristic[] }) {
  const [characteristicId, setCharacteristicId] = useState<number | "">(characteristics[0]?.id ?? "");
  const [measurements, setMeasurements] = useState<Measurement[] | null>(null);

  useEffect(() => {
    if (characteristicId === "" && characteristics.length > 0) setCharacteristicId(characteristics[0].id);
  }, [characteristics, characteristicId]);

  useEffect(() => {
    if (characteristicId === "") return;
    setMeasurements(null);
    getCharacteristicMeasurements(characteristicId, 30).then(setMeasurements).catch(() => setMeasurements([]));
  }, [characteristicId]);

  const characteristic = useMemo(
    () => characteristics.find((c) => c.id === characteristicId),
    [characteristics, characteristicId]
  );
  const data = (measurements ?? []).map((m) => ({
    ...m,
    label: new Date(m.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));
  const upper = characteristic ? characteristic.nominal_value + characteristic.tolerance : 0;
  const lower = characteristic ? characteristic.nominal_value - characteristic.tolerance : 0;

  return (
    <div className="surface" style={{ padding: 18, marginBottom: 16 }}>
      <PanelHeader
        title="Measured values"
        subtitle="Against the nominal value and tolerance band, last 30 days."
        legend={
          <>
            <LegendDot color="var(--color-success-500)" label="Pass" />
            <LegendDot color="var(--color-error-500)" label="Fail" />
          </>
        }
        filters={
          <Select
            pill
            compact
            style={{ width: 220 }}
            value={characteristicId}
            onChange={(e) => setCharacteristicId(Number(e.target.value))}
            options={characteristics.map((c) => ({ value: c.id, label: `${c.part_id} / ${c.characteristic_name}` }))}
          />
        }
      />
      {measurements === null ? (
        <Skeleton rows={1} height={200} />
      ) : data.length === 0 ? (
        <EmptyState title="No measurements yet" message="Log an inspection to start this trend." />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" vertical={false} />
            <XAxis dataKey="label" fontSize={11} tick={{ fill: "var(--color-text-tertiary)" }} axisLine={false} tickLine={false} />
            <YAxis domain={[lower - (characteristic?.tolerance ?? 0), upper + (characteristic?.tolerance ?? 0)]} fontSize={11} tick={{ fill: "var(--color-text-tertiary)" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={DARK_TOOLTIP_STYLE} />
            <ReferenceLine y={characteristic?.nominal_value} stroke="var(--color-accent-600)" strokeDasharray="4 4" label={{ value: "Nominal", fontSize: 10, fill: "var(--color-text-tertiary)" }} />
            <ReferenceLine y={upper} stroke="var(--color-error-400)" strokeDasharray="3 3" label={{ value: "Upper limit", fontSize: 10, fill: "var(--color-text-tertiary)" }} />
            <ReferenceLine y={lower} stroke="var(--color-error-400)" strokeDasharray="3 3" label={{ value: "Lower limit", fontSize: 10, fill: "var(--color-text-tertiary)" }} />
            <RechartsLine
              type="monotone"
              dataKey="measured_value"
              name="Measured value"
              stroke="var(--color-primary-400)"
              strokeWidth={1.5}
              dot={(props: { cx?: number; cy?: number; payload?: Measurement }) => {
                const { cx, cy, payload } = props;
                if (cx == null || cy == null) return <React.Fragment key={`${cx}-${cy}`} />;
                return (
                  <circle
                    key={`${cx}-${cy}`}
                    cx={cx}
                    cy={cy}
                    r={4}
                    fill={payload?.pass_fail ? "var(--color-success-500)" : "var(--color-error-500)"}
                  />
                );
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

const EMPTY_HOLD_FORM: QualityHoldIn = { part_id: "", lot_number: "", reason: "" };

/** nominal_value/tolerance are typed as `number` on the wire (CharacteristicIn),
 * but the quick-add form needs to start genuinely empty so the placeholder
 * hint shows instead of a misleading "0" — widened to `number | ""` locally
 * and coerced back to a number on submit. */
type CharacteristicFormState = Omit<CharacteristicIn, "nominal_value" | "tolerance"> & {
  nominal_value: number | "";
  tolerance: number | "";
};

const EMPTY_FORM: CharacteristicFormState = {
  part_id: "",
  characteristic_name: "",
  nominal_value: "",
  tolerance: "",
  inspection_type: "",
  line_id: "",
  station_id: "",
  defect_categories: [],
};

function characteristicToForm(c: Characteristic): CharacteristicFormState {
  return {
    part_id: c.part_id,
    characteristic_name: c.characteristic_name,
    nominal_value: c.nominal_value,
    tolerance: c.tolerance,
    inspection_type: c.inspection_type,
    line_id: c.line_id,
    station_id: c.station_id,
    defect_categories: c.defect_categories,
  };
}

const DARK_TOOLTIP_STYLE: React.CSSProperties = {
  background: "var(--color-chrome-950)",
  border: "1px solid var(--color-chrome-800)",
  borderRadius: "var(--radius-md)",
  color: "#fff",
  fontSize: 12.5,
  padding: "10px 12px",
};

/** Root-cause-hint + tolerance-drift callouts for the currently-selected
 * characteristic — see compute_defect_trend. */
function QualityHeadline({ trend }: { trend: CharacteristicTrend }) {
  return (
    <>
      {trend.is_spike && (
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
            background: "var(--color-accent-50)",
            border: "1px solid var(--color-accent-100)",
            borderLeft: "3px solid var(--color-accent-600)",
            borderRadius: "var(--radius-xl)",
            padding: "14px 16px",
            marginBottom: 14,
            boxShadow: "var(--shadow-xs)",
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: "50%",
              background: "var(--color-accent-100)",
              color: "var(--color-accent-800)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
              marginTop: 1,
            }}
          >
            <Lightbulb size={14} strokeWidth={2} />
          </div>
          <div>
            <div style={{ fontSize: 11.5, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-accent-800)", marginBottom: 4 }}>
              Root-cause hint
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55 }}>
              {trend.root_cause ?? "Defect rate spike detected, but no correlated downtime event was found on this characteristic's line."}
            </div>
          </div>
        </div>
      )}

      {trend.tolerance_drift?.is_approaching_limit && (
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
            background: "var(--color-warning-50)",
            border: "1px solid var(--color-warning-100)",
            borderLeft: "3px solid var(--color-warning-600)",
            borderRadius: "var(--radius-xl)",
            padding: "14px 16px",
            marginBottom: 14,
            boxShadow: "var(--shadow-xs)",
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: "50%",
              background: "var(--color-warning-100)",
              color: "var(--color-warning-800)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
              marginTop: 1,
            }}
          >
            <TrendingUp size={14} strokeWidth={2} />
          </div>
          <div>
            <div style={{ fontSize: 11.5, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-warning-800)", marginBottom: 4 }}>
              Drifting toward tolerance limit
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55 }}>
              Recent average measurement <span className="num">{trend.tolerance_drift.recent_avg_measured?.toFixed(3)}</span> is{" "}
              <span className="num">{Math.round((trend.tolerance_drift.recent_limit_fraction ?? 0) * 100)}%</span> of the way to the
              tolerance limit{trend.tolerance_drift.is_drifting_toward_limit ? ", and trending further out than the baseline window." : "."}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** One reusable, self-contained characteristic form for both a fresh Add
 * Characteristics entry and an existing characteristic's Edit block —
 * mirrors Production's LineForm, Predictive Maintenance's AssetForm, and
 * Inventory's ItemForm, so the four don't drift into separate
 * layouts/validations. */
function CharacteristicForm({
  initial,
  editing,
  lines,
  onCancel,
  onSave,
}: {
  initial: CharacteristicFormState;
  editing?: boolean;
  /** Production's configured lines — the Line field picks from these instead
   * of free text, matching AssetForm's Line / area field. */
  lines: Line[];
  onCancel: () => void;
  onSave: (payload: CharacteristicIn) => Promise<void>;
}) {
  const [form, setForm] = useState<CharacteristicFormState>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedLine = useMemo(() => lines.find((l) => l.line_code === form.line_id), [lines, form.line_id]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave({
        ...form,
        nominal_value: Number(form.nominal_value),
        tolerance: Number(form.tolerance),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Edit mode only: the Save button reads "Update" once something in the
  // form actually differs from the characteristic's current saved values —
  // same rule as LineForm/AssetForm/ItemForm's dirty check.
  const dirty = editing && JSON.stringify(form) !== JSON.stringify(initial);

  return (
    <div style={quickAddCardStyle}>
      <form onSubmit={handleSubmit} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        <QuickField label="Part ID">
          <input className="input" placeholder="Part ID (e.g. PN-1042)" value={form.part_id} onChange={(e) => setForm({ ...form, part_id: e.target.value })} required />
        </QuickField>
        <QuickField label="Characteristic Name">
          <input
            className="input"
            placeholder="Name (e.g. Bore Diameter)"
            value={form.characteristic_name}
            onChange={(e) => setForm({ ...form, characteristic_name: e.target.value })}
            required
          />
        </QuickField>
        <QuickField label="Nominal Value">
          <input
            className="input"
            type="number"
            step="any"
            placeholder="Nominal value (e.g. 25.4)"
            value={form.nominal_value}
            onChange={(e) => setForm({ ...form, nominal_value: e.target.value === "" ? "" : Number(e.target.value) })}
            required
          />
        </QuickField>
        <QuickField label="Tolerance (±)">
          <input
            className="input"
            type="number"
            step="any"
            placeholder="Tolerance (e.g. 0.05)"
            value={form.tolerance}
            onChange={(e) => setForm({ ...form, tolerance: e.target.value === "" ? "" : Number(e.target.value) })}
            required
          />
        </QuickField>
        <QuickField label="Inspection Type">
          <input
            className="input"
            placeholder="Inspection type (e.g. Caliper)"
            value={form.inspection_type}
            onChange={(e) => setForm({ ...form, inspection_type: e.target.value })}
          />
        </QuickField>
        <QuickField label="Line">
          <Select
            value={form.line_id}
            onChange={(e) => setForm({ ...form, line_id: e.target.value, station_id: "" })}
            options={lines.map((l) => ({ value: l.line_code, label: l.name }))}
            placeholder={lines.length === 0 ? "No lines yet — add one in Production" : "Select line"}
          />
        </QuickField>
        <QuickField label="Station">
          <Select
            value={form.station_id}
            onChange={(e) => setForm({ ...form, station_id: e.target.value })}
            options={(selectedLine?.stations ?? []).map((s) => ({ value: s, label: s }))}
            placeholder="Select station"
            disabled={!selectedLine}
          />
        </QuickField>
        <QuickField label="Defect Categories" style={{ gridColumn: "span 2" }}>
          <input
            className="input"
            placeholder="Defect categories (e.g. Scratch, Dent, Discoloration)"
            value={form.defect_categories.join(", ")}
            onChange={(e) =>
              setForm({
                ...form,
                defect_categories: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </QuickField>
        <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button className="btn-primary" style={{ minWidth: 160 }} type="submit" disabled={saving}>
            {editing ? (saving ? "Saving..." : dirty ? "Update" : "Save") : saving ? "Adding..." : "Add Characteristic"}
          </button>
        </div>
      </form>
      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 8 }}>{error}</div>}
    </div>
  );
}

/** One inspection result logged for right now — the "quick daily form"
 * alternative to building an inspection-records CSV for a single row (PRD
 * §4.9). The PRD's own CSV template lists pass_fail as a plain provided
 * column, not something auto-computed from tolerance — so the inspector
 * always states the result themselves, same as a CSV row would. */
function QuickInspectionLog({ characteristics, onLogged }: { characteristics: Characteristic[]; onLogged: () => void }) {
  const [charId, setCharId] = useState<number | "">("");
  const [measuredValue, setMeasuredValue] = useState("");
  const [result, setResult] = useState<"" | "pass" | "fail">("");
  const [defectType, setDefectType] = useState("");
  const [inspector, setInspector] = useState("");

  return (
    <QuickLogForm
      submitLabel="Log inspection"
      syncEntity="quality_inspections"
      hideSuccessMessage
      disabled={!charId || measuredValue === "" || result === ""}
      onSubmit={async () => {
        if (!charId || measuredValue === "" || result === "") return;
        await quickLogInspection(charId, {
          measured_value: Number(measuredValue),
          pass_fail: result === "pass",
          defect_type: result === "fail" && defectType ? defectType : null,
          inspector: inspector || undefined,
        });
      }}
      onSubmitted={() => {
        setMeasuredValue("");
        setDefectType("");
        setResult("");
        onLogged();
      }}
    >
      <QuickField label="Characteristic">
        <Select
          value={charId}
          onChange={(e) => setCharId(Number(e.target.value))}
          options={characteristics.map((c) => ({ value: c.id, label: `${c.part_id} / ${c.characteristic_name}` }))}
          placeholder="Select characteristic"
        />
      </QuickField>
      <QuickField label="Measured value">
        <input className="input" type="number" step="any" value={measuredValue} onChange={(e) => setMeasuredValue(e.target.value)} />
      </QuickField>
      <QuickField label="Result">
        <Select
          value={result}
          onChange={(e) => setResult(e.target.value as "" | "pass" | "fail")}
          placeholder="Inspection result"
          options={[
            { value: "pass", label: "Pass" },
            { value: "fail", label: "Fail" },
          ]}
        />
      </QuickField>
      {result === "fail" && (
        <QuickField label="Defect type">
          <input className="input" placeholder="Defect type (e.g. scratch, dent)" value={defectType} onChange={(e) => setDefectType(e.target.value)} />
        </QuickField>
      )}
      <QuickField label="Inspector">
        <input className="input" type="email" placeholder="Inspector (e.g. name@company.com)" value={inspector} onChange={(e) => setInspector(e.target.value)} />
      </QuickField>
    </QuickLogForm>
  );
}

type QualityTab = "characteristics" | "records" | "holds";

const TABS: Array<{ key: QualityTab; label: string }> = [
  { key: "characteristics", label: "Characteristics" },
  { key: "records", label: "Inspection Records" },
  { key: "holds", label: "Lot Holds" },
];

export default function QualityPage() {
  const [characteristics, setCharacteristics] = useState<Characteristic[]>([]);
  const [trends, setTrends] = useState<Record<number, CharacteristicTrend>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [freshness, setFreshness] = useState<{ last_updated_at: string | null; is_stale: boolean; expected_cadence_hours: number | null } | null>(null);

  const [tab, setTab] = useState<QualityTab>("characteristics");
  const [editingId, setEditingId] = useState<number | null>(null);
  // Bumped after every manual "add characteristic" save (or its Cancel) to
  // remount the Manual Entry form with a fresh, empty CharacteristicForm
  // instead of leaving the just-submitted values sitting in the persistent
  // tab — same fix as Assets/Lines/Items's manualFormKey.
  const [manualFormKey, setManualFormKey] = useState(0);
  const [headlineId, setHeadlineId] = useState<number | null>(null);

  const [holds, setHolds] = useState<QualityHold[]>([]);
  // History of holds that have already been cleared — the open-holds table
  // only ever shows what's still quarantined, so without this there'd be no
  // way to look back and confirm a lot was in fact released, other than
  // digging through the admin Audit Log.
  const [releasedHolds, setReleasedHolds] = useState<QualityHold[]>([]);
  const [showHoldForm, setShowHoldForm] = useState(false);
  const [holdForm, setHoldForm] = useState<QualityHoldIn>(EMPTY_HOLD_FORM);
  // Which open hold's row is expanded into "type a release note to confirm"
  // — mirrors the reason required to place a hold in the first place, so
  // clearing one always leaves a record of why the lot was safe to ship.
  const [releasingId, setReleasingId] = useState<number | null>(null);
  const [releaseNote, setReleaseNote] = useState("");
  const [releasingBusy, setReleasingBusy] = useState(false);
  // So Line ID/Station ID are picked from what's actually registered in
  // Production instead of retyped — a mismatch here used to fail silently.
  const [lines, setLines] = useState<Line[]>([]);

  // The Lot Holds form (and the release-note row) live under the Lot Holds
  // tab, but their state is on this page component, not a remountable child
  // — switching to another tab and back left the last-typed Part/Lot/Reason
  // (and any open release-note row) sitting there. Clear it whenever that
  // tab isn't the active one.
  useEffect(() => {
    if (tab !== "holds") {
      setShowHoldForm(false);
      setHoldForm(EMPTY_HOLD_FORM);
      setReleasingId(null);
      setReleaseNote("");
    }
  }, [tab]);

  async function refreshHolds() {
    setHolds(await getHolds("open"));
    setReleasedHolds(await getHolds("released"));
  }

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const list = await getCharacteristics();
      setCharacteristics(list);
      const entries = await Promise.all(list.map(async (c) => [c.id, await getCharacteristicTrend(c.id)] as const));
      const trendMap = Object.fromEntries(entries);
      setTrends(trendMap);
      setHeadlineId((prev) => {
        if (prev && list.some((c) => c.id === prev)) return prev;
        const spiking = list.find((c) => trendMap[c.id]?.is_spike);
        return (spiking ?? list[0])?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load characteristics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    refreshHolds().catch(() => undefined);
    getDashboardSummary()
      .then((summaries) => {
        const s = summaries.find((x) => x.module === "quality");
        if (s) setFreshness({ last_updated_at: s.last_updated_at, is_stale: s.is_stale, expected_cadence_hours: s.expected_cadence_hours });
      })
      .catch(() => undefined);
    productionApi.getLines().then(setLines).catch(() => setLines([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The edit form renders below the characteristics table, out of view when
  // the list is long — without this, tapping Edit updates state but the
  // user stays scrolled wherever they already were and never sees the form
  // appear (same fix as Assets/Lines/Items's scroll-to-edit-form).
  useEffect(() => {
    if (editingId != null) {
      document.getElementById("quality-edit-characteristic")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [editingId]);

  const editingCharacteristic = useMemo(() => characteristics.find((c) => c.id === editingId) ?? null, [characteristics, editingId]);

  // Same part IDs the Characteristics table itself lists — a hold should
  // point at a part this plant actually tracks, not a free-typed string
  // that risks a typo silently creating an unrelated, untracked "part".
  const knownPartIds = useMemo(
    () => Array.from(new Set(characteristics.map((c) => c.part_id))).sort(),
    [characteristics]
  );

  const headline = useMemo(
    () => characteristics.find((c) => c.id === headlineId),
    [characteristics, headlineId]
  );

  async function handleUpdateCharacteristic(payload: CharacteristicIn) {
    if (editingId == null) return;
    await updateCharacteristic(editingId, payload);
    setEditingId(null);
    await refresh();
  }

  /** Manual Entry tab in the Add Characteristics area — a plain create, kept
   * separate from handleUpdateCharacteristic (which handles editing an
   * existing characteristic from the table) so the form can be remounted
   * empty afterward instead of closing/disappearing. */
  async function handleAddCharacteristic(payload: CharacteristicIn) {
    await createCharacteristic(payload);
    await refresh();
    setManualFormKey((k) => k + 1);
  }

  async function handleDelete(id: number) {
    await deleteCharacteristic(id);
    await refresh();
  }

  async function submitHold(e: React.FormEvent) {
    e.preventDefault();
    await createHold(holdForm);
    setHoldForm(EMPTY_HOLD_FORM);
    setShowHoldForm(false);
    await refreshHolds();
  }

  async function handleReleaseHold(id: number, note: string) {
    if (!note.trim()) return;
    setReleasingBusy(true);
    try {
      await releaseHold(id, note.trim());
      setReleasingId(null);
      setReleaseNote("");
      await refreshHolds();
    } finally {
      setReleasingBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="quality" />}
        title="Quality"
        subtitle="Defect-rate trend and root-cause correlation"
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
            {/* Redundant on the Inspection Records tab itself — you're
                already there. Kept as a jump-to shortcut from the
                Characteristics tab. */}
            {tab !== "records" && (
              <RoleGuard allow={["admin", "operator"]}>
                <button className="btn-primary" onClick={() => setTab("records")}>
                  Upload Quality Data
                </button>
              </RoleGuard>
            )}
          </>
        }
      />

      {error && <div style={{ color: "var(--color-error-600)", marginBottom: 12 }}>{error}</div>}

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as QualityTab)} />

      {tab === "characteristics" && (
        <>
          {loading ? (
            <Skeleton rows={1} height={140} />
          ) : headline && trends[headline.id] ? (
            <QualityHeadline trend={trends[headline.id]} />
          ) : (
            <div style={{ marginBottom: 16 }}>
              <EmptyState title="No characteristics configured" message="Add a characteristic below, then upload inspection records to see trend data." />
            </div>
          )}

          <RoleGuard allow={["operator", "viewer"]}>
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Characteristic editing is Admin-only</span>
          </RoleGuard>

          {characteristics.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <Th>{null}</Th>
                  <Th>Part</Th>
                  <Th>Characteristic</Th>
                  <Th>Line / Station</Th>
                  <Th numeric>Recent</Th>
                  <Th numeric>Baseline</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </THead>
              <TBody>
                {characteristics.map((c) => {
                  const trend = trends[c.id];
                  const active = c.id === headlineId;
                  const lineStation = [c.line_id, c.station_id].filter(Boolean).join(" / ");
                  return (
                    <Tr key={c.id} onClick={() => setHeadlineId(c.id)} active={active}>
                      <Td>
                        {active && (
                          <span title="Currently shown above" style={{ display: "inline-flex", color: "var(--color-primary-700)" }}>
                            <Check size={14} strokeWidth={2.5} />
                          </span>
                        )}
                      </Td>
                      <Td>
                        <span style={{ fontWeight: active ? 700 : 400, color: active ? "var(--color-primary-700)" : undefined }}>
                          {c.part_id}
                        </span>
                      </Td>
                      <Td>
                        <span style={{ fontWeight: 600 }}>{c.characteristic_name}</span>
                      </Td>
                      <Td>
                        <span style={{ color: "var(--color-text-secondary)" }}>{lineStation}</span>
                      </Td>
                      <Td numeric>
                        <span
                          className="num"
                          style={trend?.is_spike ? { color: "var(--color-error-600)", fontWeight: 700 } : undefined}
                        >
                          {trend ? `${(trend.recent_rate * 100).toFixed(1)}%` : ""}
                        </span>
                      </Td>
                      <Td numeric>
                        <span style={{ color: "var(--color-text-secondary)" }}>{trend ? `${(trend.baseline_rate * 100).toFixed(1)}%` : ""}</span>
                      </Td>
                      <Td align="right">
                        <RoleGuard allow={["admin"]}>
                          <RowActions onEdit={() => setEditingId(c.id)} onDelete={() => handleDelete(c.id)} />
                        </RoleGuard>
                      </Td>
                    </Tr>
                  );
                })}
              </TBody>
            </Table>
          )}

          <RoleGuard allow={["admin"]}>
            {editingCharacteristic && (
              <div id="quality-edit-characteristic" style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 15, marginBottom: 10 }}>Edit {editingCharacteristic.characteristic_name}</h3>
                {/* Keyed on the characteristic id so switching Edit from one
                    characteristic to another remounts the form with fresh
                    initial values — same fix as Production's LineForm,
                    Predictive Maintenance's AssetForm, and Inventory's
                    ItemForm. */}
                <CharacteristicForm
                  key={editingCharacteristic.id}
                  initial={characteristicToForm(editingCharacteristic)}
                  editing
                  lines={lines}
                  onCancel={() => setEditingId(null)}
                  onSave={handleUpdateCharacteristic}
                />
              </div>
            )}
          </RoleGuard>

          <RoleGuard allow={["admin"]}>
            <div style={{ marginTop: 24 }}>
              <FormSection
                title="Add Characteristics"
                subtitle="Define a quality characteristic to inspect, or import multiple characteristics at once."
                collapsible
                defaultOpen={false}
              >
                <ConfigImportTabs
                  manual={
                    <CharacteristicForm
                      key={manualFormKey}
                      initial={EMPTY_FORM}
                      lines={lines}
                      onCancel={() => setManualFormKey((k) => k + 1)}
                      onSave={handleAddCharacteristic}
                    />
                  }
                  csv={{
                    title: "Characteristics",
                    hideHeading: true,
                    moduleLabel: "Quality",
                    ...CHARACTERISTIC_CSV_PATHS,
                    onCommitted: refresh,
                    syncEntity: "characteristics",
                    fieldChips: (
                      <FieldChips fields={["part_id", "characteristic_name", "nominal_value", "tolerance", "inspection_type", "line_id", "station_id", "defect_categories"]} />
                    ),
                  }}
                  db={{ entity: "characteristics", title: "Characteristics", moduleLabel: "Quality", onCommitted: refresh }}
                />
              </FormSection>
            </div>
          </RoleGuard>
        </>
      )}

      {tab === "records" && (
        characteristics.length > 0 ? (
          <RoleGuard allow={["admin", "operator"]}>
            <FormSection title="Inspection Records" subtitle="Log a single inspection result, or import several at once.">
              <ConfigImportTabs
                manual={<QuickInspectionLog characteristics={characteristics} onLogged={refresh} />}
                csv={{
                  title: "Inspection Records",
                  hideHeading: true,
                  moduleLabel: "Quality",
                  ...INSPECTION_RECORDS_CSV_PATHS,
                  onCommitted: refresh,
                  syncEntity: "quality_inspections",
                  fieldChips: (
                    <FieldChips fields={["part_id", "timestamp", "characteristic", "measured_value", "pass_fail", "defect_type", "line_id", "station_id", "inspector"]} />
                  ),
                }}
                db={{ entity: "quality_inspections", title: "Inspection Records", moduleLabel: "Quality", onCommitted: refresh }}
              />
            </FormSection>
          </RoleGuard>
        ) : (
          <EmptyState title="No characteristics configured" message="Configure a characteristic on the Characteristics tab first." />
        )
      )}

      {tab === "holds" && (
        <>
          <div style={{ background: "var(--color-surface-default)", border: "1px solid var(--color-border-default)", borderRadius: "var(--radius-xl)", padding: 16, marginBottom: 12, boxShadow: "var(--shadow-xs)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10, gap: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 15 }}>Lot Holds</h3>
                <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 3, lineHeight: 1.6, whiteSpace: "nowrap" }}>
                  Place a lot on hold if you suspect an issue. After QC inspection, release it with a reason.
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flex: "none" }}>
                {holds.length > 0 && (
                  // Same colors/shape as Badge's "critical" variant, just
                  // taller — matched to the button's own 42px height instead
                  // of Badge's fixed 32px, so the two sit level with each
                  // other instead of the chip looking shrunken beside it.
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      height: 42,
                      padding: "0 12px",
                      minWidth: 90,
                      borderRadius: "var(--radius-md)",
                      background: "var(--color-error-100)",
                      color: "var(--color-error-700)",
                      fontSize: 12,
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {holds.length} open
                  </span>
                )}
                <RoleGuard allow={["admin", "operator"]}>
                  <button className="btn-secondary" style={{ whiteSpace: "nowrap" }} onClick={() => setShowHoldForm((v) => !v)}>
                    {showHoldForm ? "Cancel" : "+ Place Hold"}
                  </button>
                </RoleGuard>
              </div>
            </div>

            <RoleGuard allow={["admin", "operator"]}>
              {showHoldForm && (
                <form onSubmit={submitHold} style={{ marginBottom: 12 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2.5fr", gap: 12 }}>
                    <QuickField label="Part ID">
                      <Select
                        value={holdForm.part_id}
                        onChange={(e) => setHoldForm({ ...holdForm, part_id: e.target.value })}
                        options={knownPartIds.map((p) => ({ value: p, label: p }))}
                        placeholder={knownPartIds.length === 0 ? "No parts yet — add a characteristic first" : "Select part"}
                        disabled={knownPartIds.length === 0}
                      />
                    </QuickField>
                    <QuickField label="Lot Number">
                      <input
                        className="input"
                        placeholder="Lot number (e.g. LOT-2024-118)"
                        value={holdForm.lot_number}
                        onChange={(e) => setHoldForm({ ...holdForm, lot_number: e.target.value })}
                        required
                      />
                    </QuickField>
                    <QuickField label="Reason For Hold">
                      <input
                        className="input"
                        placeholder="Reason for hold (e.g. Suspected contamination during machining)"
                        value={holdForm.reason}
                        onChange={(e) => setHoldForm({ ...holdForm, reason: e.target.value })}
                        required
                      />
                    </QuickField>
                  </div>
                  <div style={{ marginTop: 12, marginBottom: 12, display: "flex", justifyContent: "flex-end" }}>
                    <button className="btn-primary" type="submit">
                      Place Hold
                    </button>
                  </div>
                </form>
              )}
            </RoleGuard>

            {holds.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>No lots currently on hold.</div>
            ) : (
              <Table>
                <THead>
                  <tr>
                    <Th>Part</Th>
                    <Th>Lot</Th>
                    <Th>Held on</Th>
                    <Th>Reason</Th>
                    <Th align="center">Actions</Th>
                  </tr>
                </THead>
                <TBody>
                  {holds.map((h) => (
                    <React.Fragment key={h.id}>
                      <Tr>
                        <Td>{h.part_id}</Td>
                        <Td>
                          <span style={{ fontWeight: 600 }}>{h.lot_number}</span>
                        </Td>
                        <Td>{new Date(h.created_at).toLocaleString()}</Td>
                        <Td wrap>
                          <span style={{ color: "var(--color-text-secondary)" }}>{h.reason}</span>
                        </Td>
                        <Td align="center">
                          <RoleGuard allow={["admin", "operator"]}>
                            <button
                              className="btn-secondary"
                              onClick={() => {
                                setReleasingId(releasingId === h.id ? null : h.id);
                                setReleaseNote("");
                              }}
                            >
                              {releasingId === h.id ? "Cancel" : "Release"}
                            </button>
                          </RoleGuard>
                        </Td>
                      </Tr>
                      {releasingId === h.id && (
                        <tr>
                          <td colSpan={5} style={{ background: "var(--color-neutral-100)", padding: "12px 16px" }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: 6 }}>
                              Why is this lot being released?
                            </div>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <input
                                className="input"
                                style={{ flex: 1 }}
                                placeholder="Release note (e.g. Re-inspected 40 units, all passed)"
                                value={releaseNote}
                                onChange={(e) => setReleaseNote(e.target.value)}
                                autoFocus
                              />
                              <button
                                className="btn-primary"
                                disabled={!releaseNote.trim() || releasingBusy}
                                onClick={() => handleReleaseHold(h.id, releaseNote)}
                              >
                                {releasingBusy ? "Releasing..." : "Confirm Release"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </TBody>
              </Table>
            )}
          </div>

          <FormSection
            title="Released Holds"
            subtitle="Lots that were placed on QC hold and have since been approved for release."
            collapsible
            defaultOpen={false}
          >
            {releasedHolds.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>No holds have been released yet.</div>
            ) : (
              <Table>
                <THead>
                  <tr>
                    <Th>Part</Th>
                    <Th>Lot</Th>
                    <Th>Held on</Th>
                    <Th>Released</Th>
                    <Th>Held reason</Th>
                    <Th>Released reason</Th>
                  </tr>
                </THead>
                <TBody>
                  {releasedHolds.map((h) => (
                    <Tr key={h.id}>
                      <Td>{h.part_id}</Td>
                      <Td>
                        <span style={{ fontWeight: 600 }}>{h.lot_number}</span>
                      </Td>
                      <Td>{new Date(h.created_at).toLocaleString()}</Td>
                      <Td>{h.released_at ? new Date(h.released_at).toLocaleString() : ""}</Td>
                      <Td wrap>
                        <span style={{ color: "var(--color-text-secondary)" }}>{h.reason}</span>
                      </Td>
                      <Td wrap>
                        <span style={{ color: "var(--color-text-secondary)" }}>{h.release_note || "—"}</span>
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            )}
          </FormSection>
        </>
      )}
    </div>
  );
}

import React, { useEffect, useState } from "react";

import * as api from "../../api/production";
import type { DowntimeEvent, Line, LineInput, LineMetrics } from "../../api/production";
import { getDashboardSummary } from "../../api/dashboard";
import { RoleGuard } from "../../auth/ProtectedRoute";
import { DrillDownModal } from "../../components/DrillDownModal";
import { EmptyState } from "../../components/EmptyState";
import { FreshnessBadge } from "../../components/FreshnessBadge";
import { Skeleton } from "../../components/Loading";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { RowActions } from "../../components/RowActions";
import { Select } from "../../components/Select";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";
import { Tabs } from "../../components/Tabs";
import { ConfigImportTabs } from "../_shared/ConfigImportTabs";
import { CsvUploadFlow } from "../_shared/CsvUploadFlow";
import { FieldChips } from "../_shared/FieldChips";
import { FormSection } from "../_shared/FormSection";
import { QuickField, QuickLogForm } from "../_shared/QuickLogForm";
import { LineDrillDown } from "./LineDrillDown";

const EMPTY_LINE_INPUT: LineInput = {
  line_code: "",
  name: "",
  stations: [],
  products: [],
  shift_target_units: 0,
  ideal_cycle_time_seconds: 0,
};

/** Tints LineForm as an inset zone within its surrounding card (the Edit
 * block or the Add Lines section's Manual Entry tab) — same treatment as
 * the onboarding wizard's per-step quick-add forms (see
 * modules/onboarding/steps.tsx) and Predictive Maintenance's AssetForm. */
const quickAddCardStyle: React.CSSProperties = { background: "var(--color-neutral-100)", borderRadius: "var(--radius-lg)", padding: 16 };

function lineToForm(line: Line): LineInput {
  return {
    line_code: line.line_code,
    name: line.name,
    stations: line.stations,
    products: line.products,
    shift_target_units: line.shift_target_units,
    ideal_cycle_time_seconds: line.ideal_cycle_time_seconds,
  };
}

/** One reusable, self-contained line form for both a fresh Add Lines entry
 * and an existing line's Edit block — mirrors Predictive Maintenance's
 * AssetForm, so the two don't drift into separate layouts/validations, and
 * a caller can render a fresh instance (`key={...}`) per line being edited
 * or added instead of sharing one form's state across both purposes. */
function LineForm({
  initial,
  editing,
  onCancel,
  onSave,
}: {
  initial: LineInput;
  editing?: boolean;
  onCancel: () => void;
  onSave: (form: LineInput) => Promise<void>;
}) {
  const [form, setForm] = useState<LineInput>(initial);
  // Stations/Products are edited as raw text (either , or ; accepted as a
  // separator), kept separate from form.stations/form.products (the parsed
  // array) — if the input's value were the array re-joined on every
  // keystroke instead, a trailing space (or any space right before the next
  // separator) would vanish the instant it's typed, since it'd already have
  // been trimmed out of the array that gets rendered back into the field.
  // Parsing only happens at submit time, so the text you're actually
  // looking at is always exactly what you typed.
  const [stationsText, setStationsText] = useState(initial.stations.join(", "));
  const [productsText, setProductsText] = useState(initial.products.join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Accepts either , or ; as the separator — both are common conventions
  // and neither should silently fail to split just because the user reached
  // for the other one.
  function parseList(text: string): string[] {
    return text.split(/[,;]/).map((s) => s.trim()).filter(Boolean);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await onSave({ ...form, stations: parseList(stationsText), products: parseList(productsText) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Edit mode only: the Save button reads "Update" once something in the
  // form actually differs from the line's current saved values — same rule
  // as AssetForm's dirty check.
  const dirty =
    editing &&
    JSON.stringify({ ...form, stations: parseList(stationsText), products: parseList(productsText) }) !== JSON.stringify(initial);

  return (
    <div style={quickAddCardStyle}>
      <form onSubmit={handleSubmit} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        <QuickField label="Line Code">
          <input
            className="input"
            required
            placeholder="Line code (e.g. LINE-2)"
            value={form.line_code}
            onChange={(e) => setForm({ ...form, line_code: e.target.value })}
          />
        </QuickField>
        <QuickField label="Name">
          <input
            className="input"
            required
            placeholder="Name (e.g. Bottling Line)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </QuickField>
        <QuickField label="Stations">
          <input
            className="input"
            placeholder="Stations, comma-separated (e.g. Station 1, Station 2)"
            value={stationsText}
            onChange={(e) => setStationsText(e.target.value)}
          />
        </QuickField>
        <QuickField label="Products">
          <input
            className="input"
            placeholder="Products, comma-separated (e.g. Water Bottle, Juice Bottle)"
            value={productsText}
            onChange={(e) => setProductsText(e.target.value)}
          />
        </QuickField>
        <QuickField label="Shift Target Units">
          <input
            className="input"
            type="number"
            min="0"
            value={form.shift_target_units || ""}
            onChange={(e) => setForm({ ...form, shift_target_units: Number(e.target.value) })}
          />
        </QuickField>
        <QuickField label="Ideal Cycle Time (s)">
          {/* step="any" — cycle time comes from real machine throughput
              (units/min converted to seconds/unit), which is almost never a
              whole number (e.g. 3.8s). Without this, the field defaults to
              step="1" and browsers treat a decimal as invalid. */}
          <input
            className="input"
            type="number"
            step="any"
            min="0"
            value={form.ideal_cycle_time_seconds || ""}
            onChange={(e) => setForm({ ...form, ideal_cycle_time_seconds: Number(e.target.value) })}
          />
        </QuickField>
        <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {editing ? (saving ? "Saving..." : dirty ? "Update" : "Save") : saving ? "Adding..." : "Add Line"}
          </button>
        </div>
      </form>
      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 8 }}>{error}</div>}
    </div>
  );
}

/** One station's numbers logged for right now — the "quick daily form"
 * alternative to building an output-logs CSV for a single row (PRD §4.9). */
function QuickOutputLog({ lines, onLogged }: { lines: Line[]; onLogged: () => void }) {
  const [lineId, setLineId] = useState<number | "">("");
  const [station, setStation] = useState("");
  const [unitsGood, setUnitsGood] = useState("");
  const [unitsReject, setUnitsReject] = useState("");
  const [runState, setRunState] = useState<"run" | "idle" | "stop" | "">("");
  const [downtimeMinutes, setDowntimeMinutes] = useState("");
  const [downtimeReason, setDowntimeReason] = useState("");

  const selectedLine = lines.find((l) => l.id === lineId);
  // Units produced is never typed directly — it's always good + reject, so
  // there's no "produced doesn't match good+reject" data entry error for
  // quality (one of OEE's three factors) to silently inherit.
  const unitsProduced = (Number(unitsGood) || 0) + (Number(unitsReject) || 0);

  useEffect(() => {
    if (selectedLine && !selectedLine.stations.includes(station)) {
      setStation(selectedLine.stations[0] ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineId]);

  return (
    <QuickLogForm
      submitLabel="Log Output"
      hideSuccessMessage
      disabled={!lineId || !station || !runState}
      onSubmit={async () => {
        if (!lineId || !station || !runState) return;
        await api.quickLogOutput(lineId, {
          station_id: station,
          units_produced: unitsProduced,
          units_good: unitsGood ? Number(unitsGood) : 0,
          units_reject: unitsReject ? Number(unitsReject) : 0,
          run_state: runState,
          downtime_minutes: downtimeMinutes ? Number(downtimeMinutes) : 0,
          downtime_reason: downtimeReason || null,
        });
      }}
      onSubmitted={() => {
        setUnitsGood("");
        setUnitsReject("");
        setDowntimeMinutes("");
        setDowntimeReason("");
        onLogged();
      }}
    >
      <QuickField label="Line">
        <Select
          value={lineId}
          onChange={(e) => setLineId(Number(e.target.value))}
          options={lines.map((l) => ({ value: l.id, label: l.name }))}
          placeholder="Select line"
        />
      </QuickField>
      <QuickField label="Station">
        <Select
          value={station}
          onChange={(e) => setStation(e.target.value)}
          options={(selectedLine?.stations ?? []).map((s) => ({ value: s, label: s }))}
          placeholder={selectedLine ? "Select station" : "Station"}
          disabled={!selectedLine}
        />
      </QuickField>
      <QuickField label="Units good">
        <input className="input" type="number" min="0" value={unitsGood} onChange={(e) => setUnitsGood(e.target.value)} />
      </QuickField>
      <QuickField label="Units reject">
        <input className="input" type="number" min="0" value={unitsReject} onChange={(e) => setUnitsReject(e.target.value)} />
      </QuickField>
      <QuickField label="Units produced">
        {/* Always good + reject, not typed directly — see the unitsProduced
            derivation above for why. Until either of those is actually
            entered, showing a bare "0" here reads as a real, already-logged
            value rather than an untouched field — so it's masked behind a
            gray hint (same treatment as Install Date's hint overlay
            elsewhere) until there's something real to show. */}
        <div style={{ position: "relative" }}>
          <input
            className="input"
            type="number"
            value={unitsProduced}
            disabled
            style={
              unitsGood === "" && unitsReject === ""
                ? { color: "transparent", WebkitTextFillColor: "transparent" }
                : undefined
            }
          />
          {unitsGood === "" && unitsReject === "" && (
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
              Units produced
            </div>
          )}
        </div>
      </QuickField>
      <QuickField label="Run state">
        <Select
          value={runState}
          onChange={(e) => setRunState(e.target.value as "run" | "idle" | "stop")}
          options={[
            { value: "run", label: "Run" },
            { value: "idle", label: "Idle" },
            { value: "stop", label: "Stop" },
          ]}
          placeholder="Select run state"
        />
      </QuickField>
      <QuickField label="Downtime (min)">
        <input className="input" type="number" min="0" value={downtimeMinutes} onChange={(e) => setDowntimeMinutes(e.target.value)} />
      </QuickField>
      <QuickField label="Downtime reason">
        <input
          className="input"
          placeholder="Downtime reason (optional, e.g. changeover, machine jam)"
          value={downtimeReason}
          onChange={(e) => setDowntimeReason(e.target.value)}
        />
      </QuickField>
    </QuickLogForm>
  );
}

type ProductionTab = "lines" | "log";

const TABS: Array<{ key: ProductionTab; label: string }> = [
  { key: "lines", label: "Lines" },
  { key: "log", label: "Production Output" },
];

export default function ProductionPage() {
  const [tab, setTab] = useState<ProductionTab>("lines");
  const [lines, setLines] = useState<Line[]>([]);
  const [metricsByLine, setMetricsByLine] = useState<Record<number, LineMetrics>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [freshness, setFreshness] = useState<{ last_updated_at: string | null; is_stale: boolean; expected_cadence_hours: number | null } | null>(null);

  const [selectedLine, setSelectedLine] = useState<Line | null>(null);
  const [downtimeEvents, setDowntimeEvents] = useState<DowntimeEvent[]>([]);

  const [editingLine, setEditingLine] = useState<Line | null>(null);
  // Bumped after every manual "add line" save (or its Cancel) to remount
  // the Manual Entry form with a fresh, empty LineForm instead of leaving
  // the just-submitted values sitting in the persistent tab.
  const [manualFormKey, setManualFormKey] = useState(0);

  // The edit form renders below the lines table, out of view when the list
  // is long — without this, tapping Edit updates state but the user stays
  // scrolled wherever they already were and never sees the form appear.
  useEffect(() => {
    if (editingLine) {
      document.getElementById("production-edit-line")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [editingLine]);

  // Add Lines sits collapsed at the bottom of the page, below the table —
  // after a successful add, the form just resets in place and the table
  // above it (where the new row actually landed) stays off-screen, easily
  // read as "the list isn't updating." Bumped by handleAddLine; runs as an
  // effect (not inline right after the save) so it fires after React has
  // actually committed the refreshed table to the DOM, not before.
  const [justAddedLine, setJustAddedLine] = useState(0);
  useEffect(() => {
    if (justAddedLine > 0) {
      document.getElementById("production-lines-top")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [justAddedLine]);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const ls = await api.getLines();
      setLines(ls);
      const entries = await Promise.all(ls.map(async (l) => [l.id, await api.getLineMetrics(l.id)] as const));
      setMetricsByLine(Object.fromEntries(entries));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load production data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    getDashboardSummary()
      .then((summaries) => {
        const s = summaries.find((x) => x.module === "production");
        if (s) setFreshness({ last_updated_at: s.last_updated_at, is_stale: s.is_stale, expected_cadence_hours: s.expected_cadence_hours });
      })
      .catch(() => undefined);
  }, []);

  async function openLine(line: Line) {
    setSelectedLine(line);
    try {
      setDowntimeEvents(await api.getLineDowntimeEvents(line.id));
    } catch {
      setDowntimeEvents([]);
    }
  }

  async function handleUpdateLine(form: LineInput) {
    if (!editingLine) return;
    await api.updateLine(editingLine.id, form);
    setEditingLine(null);
    await loadAll();
  }

  /** Manual Entry tab in the Add Lines area — a plain create, kept separate
   * from handleUpdateLine (which handles editing an existing line from the
   * table) so the form can be remounted empty afterward instead of
   * closing/disappearing. */
  async function handleAddLine(form: LineInput) {
    await api.createLine(form);
    await loadAll();
    setManualFormKey((k) => k + 1);
    setJustAddedLine((n) => n + 1);
  }

  async function removeLine(line: Line) {
    if (!window.confirm(`Delete line ${line.name}?`)) return;
    try {
      await api.deleteLine(line.id);
      await loadAll();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Delete failed");
    }
  }

  if (error) return <EmptyState title="Couldn't load Production" message={error} />;

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="production" />}
        title="Production"
        subtitle="Track line output, OEE, and what's driving downtime across your production floor."
        actions={
          <>
            {freshness && (
              <FreshnessBadge
                lastUpdatedAt={freshness.last_updated_at}
                isStale={freshness.is_stale}
                expectedCadenceHours={freshness.expected_cadence_hours}
              />
            )}
            {/* Redundant on the Production Output tab itself — you're
                already there. Kept as a jump-to shortcut from the Lines tab. */}
            {tab !== "log" && (
              <RoleGuard allow={["admin", "operator"]}>
                <button className="btn-primary" onClick={() => setTab("log")}>
                  Upload Production Data
                </button>
              </RoleGuard>
            )}
          </>
        }
      />

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as ProductionTab)} />

      {loading && <Skeleton rows={4} />}

      {!loading && tab === "lines" && lines.length === 0 && (
        <EmptyState title="No lines configured" message="Configure a line below to get started." />
      )}

      {!loading && tab === "lines" && (
        <div id="production-lines-top">
          <RoleGuard allow={["operator", "viewer"]}>
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Line editing is Admin-only</span>
          </RoleGuard>

          {lines.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <Th>Code</Th>
                  <Th>Name</Th>
                  <Th>Stations</Th>
                  <Th>Products</Th>
                  <Th numeric align="center">Shift target</Th>
                  <Th numeric align="center">Ideal cycle (s)</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </THead>
              <TBody>
                {lines.map((line) => (
                  <Tr key={line.id} onClick={() => openLine(line)}>
                    <Td top>
                      <span className="num" style={{ fontWeight: 700, color: "var(--color-text-tertiary)" }}>{line.line_code}</span>
                    </Td>
                    <Td top>
                      <span style={{ fontWeight: 600 }}>{line.name}</span>
                    </Td>
                    <Td wrap top>
                      <span style={{ color: "var(--color-text-secondary)", fontSize: 12 }}>{line.stations.join(", ")}</span>
                    </Td>
                    <Td wrap top>
                      <span style={{ color: "var(--color-text-secondary)", fontSize: 12 }}>{line.products.join(", ") || "—"}</span>
                    </Td>
                    <Td numeric align="center" top>{line.shift_target_units}</Td>
                    <Td numeric align="center" top>{line.ideal_cycle_time_seconds}</Td>
                    <Td align="right" top>
                      <RoleGuard allow={["admin"]}>
                        <RowActions onEdit={() => setEditingLine(line)} onDelete={() => removeLine(line)} />
                      </RoleGuard>
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}

          <RoleGuard allow={["admin"]}>
            {editingLine && (
              <div id="production-edit-line" style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 15, marginBottom: 10 }}>Edit {editingLine.name}</h3>
                {/* Keyed on the line id so switching Edit from one line to
                    another remounts the form with fresh initial values —
                    same fix as Predictive Maintenance's AssetForm. */}
                <LineForm
                  key={editingLine.id}
                  initial={lineToForm(editingLine)}
                  editing
                  onCancel={() => setEditingLine(null)}
                  onSave={handleUpdateLine}
                />
              </div>
            )}
          </RoleGuard>

          <RoleGuard allow={["admin"]}>
            <div style={{ marginTop: 24 }}>
              <FormSection
                title="Add Lines"
                subtitle="Set up production lines with their stations, products, and shift targets to track production output and OEE."
                collapsible
                defaultOpen={false}
              >
                <ConfigImportTabs
                  manual={
                    <LineForm
                      key={manualFormKey}
                      initial={EMPTY_LINE_INPUT}
                      onCancel={() => setManualFormKey((k) => k + 1)}
                      onSave={handleAddLine}
                    />
                  }
                  csv={{
                    title: "Lines",
                    hideHeading: true,
                    moduleLabel: "Production",
                    templatePath: api.LINE_CSV_PATHS.templatePath,
                    mapPath: api.LINE_CSV_PATHS.mapPath,
                    validatePath: api.LINE_CSV_PATHS.validatePath,
                    commitPath: api.LINE_CSV_PATHS.commitPath,
                    onCommitted: loadAll,
                    syncEntity: "lines",
                    fieldChips: (
                      <FieldChips
                        fields={["line_code", "name", "stations", "products", "shift_target_units", "ideal_cycle_time_seconds"]}
                      />
                    ),
                  }}
                  db={{ entity: "lines", title: "Lines", moduleLabel: "Production", onCommitted: loadAll }}
                />
              </FormSection>
            </div>
          </RoleGuard>
        </div>
      )}

      {!loading && tab === "log" && (
        lines.length === 0 ? (
          <EmptyState title="No lines configured" message="Configure a line on the Lines tab first." />
        ) : (
          <RoleGuard allow={["admin", "operator"]}>
            <FormSection
              title="Production Output"
              subtitle="Log units produced, rejects, and downtime for each line and shift. This data powers your OEE and output trend charts."
            >
              <ConfigImportTabs
                manual={<QuickOutputLog lines={lines} onLogged={loadAll} />}
                csv={{
                  title: "Production Output",
                  hideHeading: true,
                  moduleLabel: "Production",
                  templatePath: "/production/csv/output-logs/template",
                  mapPath: "/production/csv/output-logs/map",
                  validatePath: "/production/csv/output-logs/validate",
                  commitPath: "/production/csv/output-logs/commit",
                  onCommitted: loadAll,
                  syncEntity: "production_output",
                  fieldChips: (
                    <FieldChips
                      fields={["line_id", "station_id", "timestamp", "units_produced", "units_good", "units_reject", "run_state", "downtime_minutes", "downtime_reason"]}
                    />
                  ),
                }}
                db={{ entity: "production_output", title: "Production Output", moduleLabel: "Production", onCommitted: loadAll }}
              />
            </FormSection>
          </RoleGuard>
        )
      )}

      {selectedLine && (
        <DrillDownModal title={`${selectedLine.name}: downtime detail`} onClose={() => setSelectedLine(null)}>
          <LineDrillDown
            line={selectedLine}
            metrics={metricsByLine[selectedLine.id]}
            events={downtimeEvents}
          />
        </DrillDownModal>
      )}
    </div>
  );
}

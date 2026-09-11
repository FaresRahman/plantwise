import React, { useEffect, useMemo, useRef, useState } from "react";
import { BadgeCheck, Boxes, Calendar, ChevronDown, ChevronRight, Clock, Factory, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  createShiftSchedule,
  deleteShiftSchedule,
  exportShiftReport,
  generateShiftReport,
  listShiftReports,
  listShiftSchedules,
  SCHEDULE_CSV_PATHS,
  ShiftReport,
  ShiftSchedule,
} from "../../api/shiftReports";
import { useAuth } from "../../auth/AuthContext";
import { Badge } from "../../components/Badge";
import { ConfigImportTabs } from "../_shared/ConfigImportTabs";
import { FieldChips } from "../_shared/FieldChips";
import { FormSection } from "../_shared/FormSection";
import { QuickField } from "../_shared/QuickLogForm";
import { EmptyState } from "../../components/EmptyState";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";
import { Tabs } from "../../components/Tabs";

/** Flags the safety-critical "hold" callout the PRD calls out explicitly —
 * a lot held with an instruction not to release it downstream. Purely a
 * presentation-layer read of text the backend already produces; no new
 * data is fetched or stored. */
function isDoNotRelease(text: string): boolean {
  return /do not release/i.test(text);
}

/** Morning/Afternoon/Evening/Night, derived from the shift's own start
 * time — meaningful regardless of what the schedule happens to be named. */
function shiftTypeLabel(windowStart: string): string {
  const hour = new Date(windowStart).getHours();
  if (hour >= 5 && hour < 12) return "Morning";
  if (hour >= 12 && hour < 17) return "Afternoon";
  if (hour >= 17 && hour < 21) return "Evening";
  return "Night";
}

/** Same module-icon mapping Card.tsx uses for the dashboard's own module
 * cards — kept local rather than imported since Card.tsx doesn't export it,
 * but the icon choice per module should still read as the same product. */
const MODULE_ICON: Record<string, LucideIcon> = {
  production: Factory,
  quality: BadgeCheck,
  predictive_maintenance: Wrench,
  inventory: Boxes,
};

/** Inset "sub-section within a card" treatment — same tinted-zone language
 * as QuickLogForm/CharacteristicForm's quick-add cards — used here so each
 * module's contribution and the next-shift-actions list read as distinct
 * containers instead of one run-on block of text. */
const reportSectionStyle: React.CSSProperties = {
  background: "var(--color-neutral-100)",
  borderRadius: "var(--radius-lg)",
  padding: "12px 14px",
};

/** Its own component (rather than fields wired straight to ShiftReportsPage's
 * own state) for the same reason CharacteristicForm/AssetForm/ItemForm/
 * LineForm are: state that lives in the *parent* survives switching
 * ConfigImportTabs to File Upload/Database Import and back, since the parent
 * itself never unmounts — only a form with its own local state actually
 * clears when File Upload is opened and Manual Entry is left, then re-picked. */
function ScheduleForm({ onSave }: { onSave: (payload: Omit<ShiftSchedule, "id">) => Promise<void> }) {
  const [name, setName] = useState("");
  const [startTime, setStartTime] = useState("06:00");
  const [endTime, setEndTime] = useState("14:00");
  const [areas, setAreas] = useState("");
  const [recipients, setRecipients] = useState("");
  // Start/end time are prefilled with a sensible default (unlike every other
  // field here, which starts genuinely empty) — until the user actually
  // interacts with one, mask its prefilled value and overlay a real hint
  // instead, the same "Install date" treatment Predictive Maintenance's
  // AssetForm uses so a guessed value never reads as a confirmed fact.
  const [startTimeTouched, setStartTimeTouched] = useState(false);
  const [endTimeTouched, setEndTimeTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const startTimeRef = useRef<HTMLInputElement>(null);
  const endTimeRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({
        name,
        start_time: `${startTime}:00`,
        end_time: `${endTime}:00`,
        areas: areas.split(",").map((a) => a.trim()).filter(Boolean),
        recipients: recipients.split(",").map((r) => r.trim()).filter(Boolean),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <QuickField label="Name" style={{ flex: "1 1 160px" }}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. Day Shift)" required />
        </QuickField>
        <QuickField label="Start time" style={{ flex: "0 1 130px" }}>
          {/* Same structural convention as Select's own chevron (see
              Select.tsx / .pw-select__chevron) and the Archive date filter
              above: the real time input is never directly clickable/typable
              — only reachable via showPicker() — so tapping this field can't
              select straight into the hour/minute/AM-PM segments. */}
          <div className="pw-select">
            <input
              ref={startTimeRef}
              type="time"
              tabIndex={-1}
              aria-hidden
              value={startTime}
              onChange={(e) => {
                setStartTime(e.target.value);
                setStartTimeTouched(true);
              }}
              style={{ position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" }}
            />
            <button
              type="button"
              className="input pw-select__native"
              style={{ textAlign: "left", cursor: "pointer", color: startTimeTouched ? "var(--color-text-primary)" : "var(--color-text-tertiary)" }}
              onClick={() => {
                try {
                  startTimeRef.current?.showPicker();
                } catch {
                  // showPicker isn't supported in every browser — nothing to
                  // fall back to since the real input is hidden.
                }
              }}
            >
              {startTimeTouched ? startTime : "Start time"}
            </button>
            <Clock size={14} strokeWidth={2} className="pw-select__chevron" aria-hidden="true" />
          </div>
        </QuickField>
        <QuickField label="End time" style={{ flex: "0 1 130px" }}>
          <div className="pw-select">
            <input
              ref={endTimeRef}
              type="time"
              tabIndex={-1}
              aria-hidden
              value={endTime}
              onChange={(e) => {
                setEndTime(e.target.value);
                setEndTimeTouched(true);
              }}
              style={{ position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" }}
            />
            <button
              type="button"
              className="input pw-select__native"
              style={{ textAlign: "left", cursor: "pointer", color: endTimeTouched ? "var(--color-text-primary)" : "var(--color-text-tertiary)" }}
              onClick={() => {
                try {
                  endTimeRef.current?.showPicker();
                } catch {
                  // showPicker isn't supported in every browser — nothing to
                  // fall back to since the real input is hidden.
                }
              }}
            >
              {endTimeTouched ? endTime : "End time"}
            </button>
            <Clock size={14} strokeWidth={2} className="pw-select__chevron" aria-hidden="true" />
          </div>
        </QuickField>
        <QuickField label="Areas" style={{ flex: "1 1 180px" }}>
          <input className="input" value={areas} onChange={(e) => setAreas(e.target.value)} placeholder="Areas (e.g. Line 2, Line 3)" />
        </QuickField>
        <QuickField label="Recipients" style={{ flex: "1 1 220px" }}>
          <input className="input" value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="Recipients (e.g. supervisor@plant.com)" />
        </QuickField>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Adding..." : "Add Schedule"}
        </button>
      </div>
    </form>
  );
}

type ShiftReportsTab = "reports" | "schedules";

const TABS: Array<{ key: ShiftReportsTab; label: string }> = [
  { key: "reports", label: "Reports" },
  { key: "schedules", label: "Shift Schedules" },
];

export default function ShiftReportsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const canGenerate = user?.role === "admin" || user?.role === "operator";

  const [tab, setTab] = useState<ShiftReportsTab>("reports");
  const [schedules, setSchedules] = useState<ShiftSchedule[] | null>(null);
  const [reports, setReports] = useState<ShiftReport[] | null>(null);
  const [dateFilter, setDateFilter] = useState("");
  const dateFilterRef = useRef<HTMLInputElement>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<number | null>(null);
  // Bumped after every successful schedule add to remount ScheduleForm with a
  // fresh, empty instance — same fix as Assets/Lines/Items/Characteristics's
  // manualFormKey.
  const [manualFormKey, setManualFormKey] = useState(0);

  // Switching tabs (or navigating away and back to this page, which remounts
  // it) should never leave a stale date filter silently narrowing the
  // Archive list — clear it whenever the Reports tab isn't the active one.
  useEffect(() => {
    if (tab !== "reports") setDateFilter("");
  }, [tab]);

  function refresh() {
    listShiftSchedules()
      .then(setSchedules)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load schedules"));
    listShiftReports()
      .then(setReports)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load reports"));
  }

  useEffect(refresh, []);

  async function handleCreateSchedule(payload: Omit<ShiftSchedule, "id">) {
    await createShiftSchedule(payload);
    setManualFormKey((k) => k + 1);
    refresh();
  }

  async function handleGenerate(scheduleId: number) {
    setGenerating(scheduleId);
    try {
      await generateShiftReport(scheduleId);
      refresh();
    } finally {
      setGenerating(null);
    }
  }

  const filteredReports = useMemo(() => {
    if (!reports) return [];
    if (!dateFilter) return reports;
    return reports.filter((r) => new Date(r.window_start).toLocaleDateString("en-CA") === dateFilter);
  }, [reports, dateFilter]);

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="shift" />}
        title="Shift Reports"
        subtitle="Shift handover reports with follow-up actions for the next team"
        actions={
          /* Redundant on the Shift Schedules tab itself — you're already
             there. Kept as a jump-to shortcut from the Reports tab. */
          tab !== "schedules" && isAdmin ? (
            <button className="btn-primary" onClick={() => setTab("schedules")}>
              Manage Shift Schedules
            </button>
          ) : undefined
        }
      />

      {error && <EmptyState title="Couldn't load shift reports" message={error} />}

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as ShiftReportsTab)} />

      {tab === "reports" && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
            <h3 style={{ fontSize: 15, margin: 0 }}>Archive</h3>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {/* Same structural convention as Select's own chevron (see
                  Select.tsx / .pw-select__chevron): a real control reserving
                  padding on one side, with a fixed, absolutely-positioned
                  icon laid on top — not a manually-gapped flex row — so this
                  reads as the same kind of control as every dropdown filter
                  elsewhere in the app. */}
              <div className="pw-select" style={{ width: 128 }}>
                {/* The real date input is never directly clickable/typable —
                    it sits invisibly behind the button below and only ever
                    opens its native calendar dropdown via showPicker(). That
                    keeps this from ever exposing the raw dd/mm/yyyy segment
                    editing a plain `<input type="date">` would otherwise let
                    someone tap or type into. */}
                <input
                  ref={dateFilterRef}
                  type="date"
                  tabIndex={-1}
                  aria-hidden
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value)}
                  style={{ position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" }}
                />
                <button
                  type="button"
                  className="input pw-select__native"
                  style={{
                    height: 32,
                    fontSize: 13,
                    textAlign: "left",
                    cursor: "pointer",
                    color: dateFilter ? "var(--color-text-primary)" : "var(--color-text-tertiary)",
                  }}
                  onClick={() => {
                    try {
                      dateFilterRef.current?.showPicker();
                    } catch {
                      // showPicker isn't supported in every browser — nothing
                      // to fall back to here since the real input is hidden,
                      // but that combination (a browser old enough to lack
                      // showPicker) isn't one this app targets.
                    }
                  }}
                >
                  {dateFilter ? new Date(dateFilter).toLocaleDateString() : "Date"}
                </button>
                {!dateFilter && <Calendar size={14} strokeWidth={2} className="pw-select__chevron" aria-hidden="true" />}
              </div>
              {dateFilter && (
                <button className="btn-secondary btn-compact" onClick={() => setDateFilter("")}>
                  Clear
                </button>
              )}
            </div>
          </div>
          {reports && reports.length === 0 && (
            <div style={{ marginBottom: 18 }}>
              <EmptyState title="No shift reports yet" message="Generate one from a schedule on the Shift Schedules tab." />
            </div>
          )}
          {reports && reports.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 18 }}>
              {filteredReports.length === 0 ? (
                <EmptyState title="No reports for this date" message="Try a different date, or clear the filter." />
              ) : (
              filteredReports.map((r) => {
                const hasHold = r.next_shift_actions.some(isDoNotRelease);
                return (
                  <div key={r.id} className="surface" style={{ padding: 14 }}>
                    <div
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", gap: 12, flexWrap: "wrap" }}
                      onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {expanded === r.id ? (
                          <ChevronDown size={15} strokeWidth={2} style={{ color: "var(--color-text-tertiary)", flex: "none" }} />
                        ) : (
                          <ChevronRight size={15} strokeWidth={2} style={{ color: "var(--color-text-tertiary)", flex: "none" }} />
                        )}
                        <span className="num" style={{ fontSize: 14, fontWeight: 600 }}>
                          {new Date(r.window_start).toLocaleString()} to {new Date(r.window_end).toLocaleTimeString()}
                        </span>
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <Badge variant="info">{shiftTypeLabel(r.window_start)}</Badge>
                        {r.next_shift_actions.length > 0 ? (
                          <Badge variant={hasHold ? "critical" : "warning"}>
                            <span className="num">{r.next_shift_actions.length}</span>&nbsp;next-shift action
                            {r.next_shift_actions.length === 1 ? "" : "s"}
                          </Badge>
                        ) : (
                          <Badge variant="ok">No open actions</Badge>
                        )}
                        <button
                          className="btn-secondary btn-compact"
                          onClick={(e) => {
                            e.stopPropagation();
                            exportShiftReport(r.id, r.window_start);
                          }}
                        >
                          Export
                        </button>
                      </span>
                    </div>
                    {expanded === r.id && (
                      <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--color-border-subtle)", display: "flex", flexDirection: "column", gap: 8 }}>
                        {r.compiled_content.map((c) => {
                          const critical = isDoNotRelease(c.summary_text || "");
                          const Icon = MODULE_ICON[c.module] ?? Factory;
                          return (
                            <div key={c.module} style={{ ...reportSectionStyle, display: "flex", gap: 10, alignItems: "flex-start" }}>
                              <div
                                style={{
                                  width: 26,
                                  height: 26,
                                  borderRadius: "var(--radius-md)",
                                  background: "var(--color-surface-default)",
                                  color: "var(--color-text-tertiary)",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  flex: "none",
                                  marginTop: 1,
                                }}
                              >
                                <Icon size={14} strokeWidth={1.8} />
                              </div>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, flexWrap: "wrap" }}>
                                  <h4 style={{ fontSize: 13, margin: 0, textTransform: "capitalize" }}>{c.module.replace(/_/g, " ")}</h4>
                                  {critical && <Badge variant="critical">Do not release</Badge>}
                                </div>
                                <p
                                  style={{
                                    fontSize: 13,
                                    margin: 0,
                                    color: critical ? "var(--color-error-700)" : "var(--color-text-secondary)",
                                    fontWeight: critical ? 600 : 400,
                                  }}
                                >
                                  {c.summary_text || "No update."}
                                </p>
                              </div>
                            </div>
                          );
                        })}
                        <div style={reportSectionStyle}>
                          <h4 style={{ fontSize: 13, margin: "0 0 8px" }}>Next-shift actions</h4>
                          {r.next_shift_actions.length === 0 ? (
                            <p style={{ fontSize: 13, margin: 0, color: "var(--color-text-secondary)" }}>No outstanding actions.</p>
                          ) : (
                            <ul style={{ fontSize: 13, margin: 0, paddingLeft: 20 }}>
                              {r.next_shift_actions.map((a, i) => {
                                const critical = isDoNotRelease(a);
                                return (
                                  <li
                                    key={i}
                                    style={{
                                      marginBottom: 4,
                                      color: critical ? "var(--color-error-700)" : "inherit",
                                      fontWeight: critical ? 600 : 400,
                                    }}
                                  >
                                    {critical && <Badge variant="critical">Do not release</Badge>} {a}
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
              )}
            </div>
          )}
        </>
      )}

      {tab === "schedules" && (
        <>
          {schedules && schedules.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <Table>
                <THead>
                  <tr>
                    <Th>Schedule</Th>
                    <Th numeric>Time window</Th>
                    <Th>Areas</Th>
                    <Th align="right">Actions</Th>
                  </tr>
                </THead>
                <TBody>
                  {schedules.map((s) => (
                    <Tr key={s.id}>
                      <Td wrap>
                        <strong>{s.name}</strong>
                      </Td>
                      <Td numeric>
                        {s.start_time.slice(0, 5)} to {s.end_time.slice(0, 5)}
                      </Td>
                      <Td wrap>{s.areas.length > 0 ? s.areas.join(", ") : ""}</Td>
                      <Td>
                        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                          {canGenerate && (
                            <button
                              className="btn-secondary"
                              style={{ width: 130, height: 42 }}
                              onClick={() => handleGenerate(s.id)}
                              disabled={generating === s.id}
                            >
                              {generating === s.id ? "Generating..." : "Generate Now"}
                            </button>
                          )}
                          {isAdmin && (
                            <button
                              className="btn-danger"
                              onClick={() => {
                                if (!window.confirm(`Remove the "${s.name}" shift schedule? This can't be undone.`)) return;
                                deleteShiftSchedule(s.id).then(refresh);
                              }}
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            </div>
          )}

          {isAdmin && (
            <FormSection
              title="Add Shift Schedule"
              subtitle="Set up a shift so handover reports generate automatically at shift end, or import several at once."
              collapsible
              defaultOpen={false}
            >
              <ConfigImportTabs
                manual={<ScheduleForm key={manualFormKey} onSave={handleCreateSchedule} />}
                csv={{
                  title: "Shift Schedules",
                  hideHeading: true,
                  moduleLabel: "Shift Reports",
                  templatePath: SCHEDULE_CSV_PATHS.templatePath,
                  mapPath: SCHEDULE_CSV_PATHS.mapPath,
                  validatePath: SCHEDULE_CSV_PATHS.validatePath,
                  commitPath: SCHEDULE_CSV_PATHS.commitPath,
                  onCommitted: refresh,
                  syncEntity: "schedules",
                  fieldChips: <FieldChips fields={["name", "start_time", "end_time", "areas", "recipients"]} />,
                }}
                db={{ entity: "schedules", title: "Shift Schedules", moduleLabel: "Shift Reports", onCommitted: refresh }}
              />
            </FormSection>
          )}
        </>
      )}
    </div>
  );
}

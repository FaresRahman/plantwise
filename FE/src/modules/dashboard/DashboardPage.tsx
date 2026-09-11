import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { getDashboardSummary, ModuleSummary } from "../../api/dashboard";
import { getLineMetrics, getLineOeeHistory, getLines } from "../../api/production";
import { Characteristic, getCharacteristics } from "../../api/quality";
import { useAuth } from "../../auth/AuthContext";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Skeleton } from "../../components/Loading";
import { QualityMeasurementsPanel } from "../quality/QualityPage";

// Same small-caps convention the onboarding wizard's steps.tsx already uses
// to mark a new section within a page — reused here, not reinvented, so
// "Production" and "Quality" read as the same kind of divider a user has
// already seen elsewhere in the app.
const eyebrowStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: ".06em",
  color: "var(--color-text-tertiary)",
  margin: "30px 0 12px",
  paddingTop: 20,
  borderTop: "1px solid var(--color-border-default)",
};

interface OeeSummary {
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  hasData: boolean;
}

/** OEE meter fill/track color by the plant's own severity bands — World-class
 * (>=85%), typical (>=60%), and below. The unfilled track is a lighter step
 * of the *same* ramp as the fill (not a generic neutral), per the "meter"
 * spec: state should read across the whole bar, not just the filled part. */
function oeeSeverity(oeePct: number): { fill: string; track: string } {
  if (oeePct >= 85) return { fill: "var(--color-success-600)", track: "var(--color-success-100)" };
  if (oeePct >= 60) return { fill: "var(--color-warning-600)", track: "var(--color-warning-100)" };
  return { fill: "var(--color-error-600)", track: "var(--color-error-100)" };
}

const TOOLTIP_STYLE = {
  background: "var(--color-chrome-950)",
  border: "1px solid var(--color-chrome-800)",
  borderRadius: "var(--radius-md)",
  color: "#fff",
  fontSize: 12.5,
  padding: "10px 12px",
};

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** Index of the last reported (non-null) point in the trend — the OEE line
 * gets one emphasized dot there instead of a dot on every point, so the
 * chart reads as a trend with a "you are here" marker, not a scatter. */
function lastReportedIndex(points: Array<{ oee: number | null }>): number {
  for (let i = points.length - 1; i >= 0; i--) {
    if (points[i].oee != null) return i;
  }
  return -1;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [summaries, setSummaries] = useState<ModuleSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oee, setOee] = useState<OeeSummary | null | undefined>(undefined);
  const [oeeTrend, setOeeTrend] = useState<Array<{ date: string; oee: number | null }> | null | undefined>(undefined);
  const [actualVsTarget, setActualVsTarget] = useState<Array<{ date: string; actual: number; target: number }> | null | undefined>(undefined);
  const [qualityCharacteristics, setQualityCharacteristics] = useState<Characteristic[]>([]);

  useEffect(() => {
    getDashboardSummary()
      .then(setSummaries)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load dashboard"));
  }, []);

  useEffect(() => {
    getCharacteristics().then(setQualityCharacteristics).catch(() => setQualityCharacteristics([]));
  }, []);

  useEffect(() => {
    async function loadOee() {
      try {
        const lines = await getLines();
        const metrics = await Promise.all(lines.map((l) => getLineMetrics(l.id)));
        const reporting = metrics.filter((m) => m.has_data);
        if (reporting.length === 0) {
          setOee({ availability: 0, performance: 0, quality: 0, oee: 0, hasData: false });
          return;
        }
        const avg = (pick: (m: (typeof reporting)[number]) => number) =>
          reporting.reduce((sum, m) => sum + pick(m), 0) / reporting.length;
        setOee({
          availability: avg((m) => m.availability),
          performance: avg((m) => m.performance),
          quality: avg((m) => m.quality),
          oee: avg((m) => m.oee),
          hasData: true,
        });
      } catch {
        setOee(null);
      }
    }
    loadOee();
  }, []);

  useEffect(() => {
    async function loadTrends() {
      try {
        const lines = await getLines();
        if (lines.length === 0) {
          setOeeTrend([]);
          setActualVsTarget([]);
          return;
        }
        // One shared fetch — each line's own 14-day history — feeds both
        // trend charts below instead of hitting the same endpoint twice.
        const histories = await Promise.all(lines.map((l) => getLineOeeHistory(l.id, 14)));
        const byDate = new Map<string, { oeeSum: number; oeeCount: number; actual: number; target: number }>();
        for (const history of histories) {
          for (const point of history) {
            const entry = byDate.get(point.date) ?? { oeeSum: 0, oeeCount: 0, actual: 0, target: 0 };
            // Actual vs target sums every line regardless of whether it
            // reported — a line that logged nothing still had a target that
            // day, and that's a real gap, not something to hide by excluding it.
            entry.actual += point.total_units;
            entry.target += point.shift_target_units;
            // OEE%, unlike a unit count, can't be meaningfully averaged in a
            // line that didn't report as a 0 — so it's excluded here, same
            // "average across reporting lines" rule the snapshot gauge uses.
            if (point.total_units > 0) {
              entry.oeeSum += point.oee;
              entry.oeeCount += 1;
            }
            byDate.set(point.date, entry);
          }
        }
        // All lines are queried for the same 14-day window, so any one
        // line's date sequence is the canonical axis.
        const dates = histories[0]?.map((p) => p.date) ?? [];
        setOeeTrend(
          dates.map((date) => {
            const entry = byDate.get(date);
            // No line reported this day — a gap, not a 0%, so the line
            // chart shows a break instead of implying a real bad reading.
            return { date, oee: entry && entry.oeeCount > 0 ? Math.round((entry.oeeSum / entry.oeeCount) * 100) : null };
          })
        );
        setActualVsTarget(
          dates.map((date) => {
            const entry = byDate.get(date);
            return { date, actual: entry?.actual ?? 0, target: entry?.target ?? 0 };
          })
        );
      } catch {
        setOeeTrend(null);
        setActualVsTarget(null);
      }
    }
    loadTrends();
  }, []);

  if (error) return <EmptyState title="Couldn't load dashboard" message={error} />;
  if (!summaries) return <Skeleton rows={4} height={80} />;

  const firstName = user?.full_name?.split(" ")[0] ?? "there";

  return (
    <div style={{ maxWidth: 1080 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 21 }}>
            {greeting()}, {firstName}
          </h1>
          <div style={{ fontSize: 13.5, color: "var(--color-text-secondary)", marginTop: 3 }}>One view of your plant. Always current.</div>
        </div>
        <button className="btn-outline-accent" onClick={() => navigate("/chat")}>
          <Sparkles size={15} strokeWidth={2} />
          Ask the AI
        </button>
      </div>

      {/* row 1 — the same Card every module page's own tile grid uses,
          instead of a duplicated one-off tile that silently dropped every
          metric past the first. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 28 }}>
        {summaries.map((s) => (
          <Card key={s.module} summary={s} />
        ))}
      </div>

      <div style={eyebrowStyle}>Production</div>

      {/* the plant's one mandatory manufacturing KPI (OEE, broken into
          Availability/Performance/Quality) paired with its own trend, so
          today's snapshot and the last 14 days read as one story instead of
          two disconnected panels. */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 1fr) 2fr", gap: 16 }}>
        <div className="surface" style={{ padding: 22 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Production OEE</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2, marginBottom: 4 }}>
            Overall Equipment Effectiveness, averaged across reporting lines today.
          </div>
          {oee === undefined ? (
            <Skeleton rows={1} height={170} />
          ) : oee === null || !oee.hasData ? (
            <EmptyState title="No output logged" message="Log today's output on Production to see OEE here." />
          ) : (
            <>
              <div style={{ position: "relative" }}>
                <ResponsiveContainer width="100%" height={170}>
                  <PieChart>
                    <Pie
                      data={[
                        { key: "value", value: Math.round(oee.oee * 100) },
                        { key: "remainder", value: 100 - Math.round(oee.oee * 100) },
                      ]}
                      dataKey="value"
                      nameKey="key"
                      cx="50%"
                      cy="92%"
                      startAngle={180}
                      endAngle={0}
                      innerRadius={72}
                      outerRadius={104}
                      stroke="var(--color-surface-default)"
                      strokeWidth={3}
                    >
                      <Cell fill={oeeSeverity(Math.round(oee.oee * 100)).fill} />
                      <Cell fill={oeeSeverity(Math.round(oee.oee * 100)).track} />
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ position: "absolute", left: 0, right: 0, bottom: 6, textAlign: "center", pointerEvents: "none" }}>
                  <div className="num" style={{ fontSize: 30, fontWeight: 800, lineHeight: 1, color: "var(--color-text-primary)" }}>
                    {Math.round(oee.oee * 100)}%
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginTop: 2 }}>OEE today</div>
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "center", gap: 14, flexWrap: "wrap", marginTop: 6, paddingTop: 14, borderTop: "1px solid var(--color-border-subtle)" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)" }}>
                  Availability <span className="num" style={{ color: "var(--color-text-primary)" }}>{Math.round(oee.availability * 100)}%</span>
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)" }}>
                  Performance <span className="num" style={{ color: "var(--color-text-primary)" }}>{Math.round(oee.performance * 100)}%</span>
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)" }}>
                  Quality <span className="num" style={{ color: "var(--color-text-primary)" }}>{Math.round(oee.quality * 100)}%</span>
                </span>
              </div>
            </>
          )}
        </div>

        {/* the trend companion to the gauge on the left — same
            "average across reporting lines" rule, extended per day instead
            of collapsed to a single snapshot. */}
        <div className="surface" style={{ padding: 22 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Production OEE trend</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2, marginBottom: 4 }}>
            Plant-wide average OEE over the last 14 days, across all reporting lines.
          </div>
          {oeeTrend === undefined ? (
            <Skeleton rows={1} height={200} />
          ) : oeeTrend === null || oeeTrend.every((p) => p.oee == null) ? (
            <EmptyState title="No output logged" message="Log output on Production to see the OEE trend here." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={oeeTrend} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                  tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  axisLine={{ stroke: "var(--color-border-subtle)" }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                  tickFormatter={(v: number) => `${v}%`}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                />
                <ReferenceLine
                  y={85}
                  stroke="var(--color-success-400)"
                  strokeDasharray="4 4"
                  label={{ value: "World-class", position: "insideTopRight", fontSize: 10.5, fill: "var(--color-text-tertiary)" }}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(value) => [`${value}%`, "OEE"]}
                  labelFormatter={(d) => new Date(String(d)).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                />
                <Line
                  type="monotone"
                  dataKey="oee"
                  stroke="var(--color-primary-600)"
                  strokeWidth={2}
                  dot={(dotProps: { cx?: number; cy?: number; index?: number }) => (
                    <circle
                      key={dotProps.index}
                      cx={dotProps.cx ?? 0}
                      cy={dotProps.cy ?? 0}
                      r={dotProps.index === lastReportedIndex(oeeTrend) ? 4.5 : 0}
                      fill="var(--color-primary-600)"
                      stroke="var(--color-surface-default)"
                      strokeWidth={2}
                    />
                  )}
                  activeDot={{ r: 4 }}
                  connectNulls={false}
                  name="OEE"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* row 4 — actual output vs. each day's target, summed across every
          line (not just reporting ones — a line that logged nothing still
          had a target, and that's a real gap worth seeing, unlike OEE% which
          can't be meaningfully averaged in for a non-reporting line). */}
      <div className="surface" style={{ padding: 22, marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Actual vs. target output</div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2, marginBottom: 4 }}>
          Plant-wide units produced against the shift target, summed across all lines, over the last 14 days.
        </div>
        {actualVsTarget === undefined ? (
          <Skeleton rows={1} height={200} />
        ) : actualVsTarget === null || actualVsTarget.every((p) => p.actual === 0 && p.target === 0) ? (
          <EmptyState title="No output logged" message="Log output on Production, and set a shift target on a line, to see this here." />
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={actualVsTarget} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                axisLine={{ stroke: "var(--color-border-subtle)" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={(d) => new Date(String(d)).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} iconType="plainline" />
              <Bar dataKey="actual" name="Actual" fill="var(--color-primary-600)" radius={[3, 3, 0, 0]} maxBarSize={22} />
              <Line
                type="monotone"
                dataKey="target"
                name="Target"
                stroke="var(--color-text-tertiary)"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
                activeDot={{ r: 4 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Quality's measured-values trend, the same panel Quality's own page
          shows, moved here so a look at "how's quality doing" doesn't
          require drilling into that page first. */}
      {qualityCharacteristics.length > 0 && (
        <>
          <div style={eyebrowStyle}>Quality</div>
          <QualityMeasurementsPanel characteristics={qualityCharacteristics} />
        </>
      )}
    </div>
  );
}

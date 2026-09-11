import React from "react";

import type { DowntimeEvent, Line, LineMetrics } from "../../api/production";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";

/** Downtime timeline, rendered inside DrillDownModal when a LineCard is
 * clicked. Trend/analytics charts for this line live on the Dashboard's
 * Production panel instead (see modules/dashboard/AnalyticsPanels.tsx) —
 * this modal keeps only the point-in-time summary and the event log, which
 * aren't charts and belong with the line's own detail view. */
export function LineDrillDown({
  metrics,
  events,
}: {
  line: Line;
  metrics?: LineMetrics;
  events: DowntimeEvent[];
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {metrics && !metrics.has_data && (
        <p style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>
          No output logged for this window yet.
        </p>
      )}
      {metrics && metrics.has_data && (
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", fontSize: 13 }}>
          <div>
            <span className="num" style={{ fontWeight: 700 }}>{metrics.total_units}</span> / <span className="num">{metrics.shift_target_units}</span> units
          </div>
          <div>
            OEE <span className="num" style={{ fontWeight: 700 }}>{Math.round(metrics.oee * 100)}%</span>
          </div>
          <div>
            Availability <span className="num">{Math.round(metrics.availability * 100)}%</span>
          </div>
          <div>
            Performance <span className="num">{Math.round(metrics.performance * 100)}%</span>
          </div>
          <div>
            Quality <span className="num">{Math.round(metrics.quality * 100)}%</span>
          </div>
        </div>
      )}

      {metrics && metrics.downtime_pareto.length > 0 && (
        <div>
          <h4 style={{ marginBottom: 8, fontSize: 13 }}>Downtime, this window</h4>
          <Table>
            <THead>
              <tr>
                <Th>Station</Th>
                <Th>Reason</Th>
                <Th numeric>Minutes</Th>
              </tr>
            </THead>
            <TBody>
              {metrics.downtime_pareto.map((p, i) => (
                <Tr key={i}>
                  <Td>{p.station_id}</Td>
                  <Td>{p.downtime_reason}</Td>
                  <Td numeric>{p.downtime_minutes}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      <div>
        <h4 style={{ marginBottom: 8, fontSize: 13 }}>Downtime timeline</h4>
        {events.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>No downtime events in this window.</p>
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Station</Th>
                <Th>Reason</Th>
                <Th numeric>Minutes</Th>
              </tr>
            </THead>
            <TBody>
              {events.map((e, i) => (
                <Tr key={i}>
                  <Td>{new Date(e.timestamp).toLocaleString()}</Td>
                  <Td>{e.station_id}</Td>
                  <Td>{e.downtime_reason ?? ""}</Td>
                  <Td numeric>{e.downtime_minutes}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </div>
    </div>
  );
}

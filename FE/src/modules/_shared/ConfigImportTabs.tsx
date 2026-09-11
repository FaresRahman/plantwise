import React, { useEffect, useState } from "react";

import { CsvUploadFlow } from "./CsvUploadFlow";
import { DatabaseImportWizard } from "./DatabaseImportWizard";
import { useActiveSyncSchedule, useIsDbConnected } from "./useSyncStatus";

type Mode = "manual" | "file" | "database";

interface ConfigImportTabsProps {
  /** The page's own quick-add form (+ recently-added chips) for "Manual
   * Entry" as a source alongside File Upload/Database Import. Omit this on
   * pages where manual entry is a separate, persistent view (e.g. a full
   * registry table with its own add/edit/delete) rather than a competing
   * one-off "how do I get data in" choice — there this stays a plain
   * File Upload / Database Import switch, same as before. */
  manual?: React.ReactNode;
  csv: React.ComponentProps<typeof CsvUploadFlow>;
  /** Omit this when a database connection for this data is set up in one
   * place (onboarding's Data Source step, or Admin > Data Sources) instead
   * of separately on every page — most callers now leave this unset. Even
   * when set, this tab only actually shows before the tenant has connected
   * any database at all — once one exists, Admin > Data Sources is the one
   * place left to map more entities from it (see useIsDbConnected). */
  db?: React.ComponentProps<typeof DatabaseImportWizard>;
}

const ALL_TABS: Array<{ key: Mode; label: string }> = [
  { key: "manual", label: "Manual Entry" },
  { key: "file", label: "File Upload" },
  { key: "database", label: "Database Import" },
];

/**
 * The configuration sources (Manual Entry / File Upload / Database Import)
 * are mutually exclusive — a single choice, not several sections stacked on
 * the page at once. Pick one, see one.
 */
export function ConfigImportTabs({ manual, csv, db }: ConfigImportTabsProps) {
  // Once this entity is already connected and syncing from a database, the
  // Database Import tab has nothing left to offer, mapping it again would
  // just re-do what's already running, so it's hidden rather than shown
  // alongside a redundant "syncing automatically" banner.
  const activeSync = useActiveSyncSchedule(csv.syncEntity ?? "__none");
  // And once the tenant has connected *any* database, re-connecting from a
  // random module page is a second, confusing path to the same place —
  // Admin > Data Sources already covers every remaining entity from there.
  const isDbConnected = useIsDbConnected();
  // isDbConnected === false, not just falsy — while it's still null
  // (the one-time cache warm-up), that must NOT be read the same as "no
  // connection", or the tab flashes visible and then disappears once the
  // real answer arrives instead of just staying hidden until it's known.
  const dbAvailable = !!db && !activeSync && isDbConnected === false;
  const tabs = ALL_TABS.filter((t) => (t.key === "manual" ? !!manual : t.key === "database" ? dbAvailable : true));
  const [mode, setMode] = useState<Mode>(manual ? "manual" : "file");

  useEffect(() => {
    if (mode === "database" && !dbAvailable) setMode(manual ? "manual" : "file");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dbAvailable]);

  return (
    <div>
      {/* One banner for whichever source is active — Manual Entry and File
          Upload used to each show their own identical copy of this notice;
          shown once here, above the source switcher, since it's true
          regardless of which of the two the user has open. */}
      {activeSync && (
        <div
          style={{
            background: "var(--color-accent-50)",
            border: "1px solid var(--color-accent-200)",
            borderRadius: "var(--radius-lg)",
            padding: "10px 14px",
            marginBottom: 14,
            fontSize: 12.5,
            color: "var(--color-accent-800)",
            lineHeight: 1.5,
          }}
        >
          This data is syncing automatically from your database every {activeSync.interval_minutes} min. Entering or
          uploading data here is still fine for a one-off correction or backfill. It will not affect the sync.
        </div>
      )}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={mode === tab.key ? "seg-btn seg-btn--active" : "seg-btn"}
            onClick={() => setMode(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {mode === "manual" && manual}
      {mode === "file" && <CsvUploadFlow {...csv} />}
      {mode === "database" && dbAvailable && <DatabaseImportWizard {...db} />}
    </div>
  );
}

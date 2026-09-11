import { useEffect, useState } from "react";

import { listSavedConnections, listSyncSchedules, type SyncSchedule } from "../../api/dbImport";

/** Whether a given db_import entity key (e.g. "sensor_readings") currently
 * has an enabled continuous-sync schedule — used to tell manual entry/CSV
 * upload UIs to note that this data is already arriving automatically,
 * without removing them (still useful for one-off corrections or events the
 * source database doesn't capture). */
export function useActiveSyncSchedule(entity: string): SyncSchedule | null {
  const [schedule, setSchedule] = useState<SyncSchedule | null>(null);

  useEffect(() => {
    listSyncSchedules()
      .then((all) => setSchedule(all.find((s) => s.entity === entity && s.enabled) ?? null))
      .catch(() => undefined); // best-effort — a fetch failure here shouldn't block the manual entry/upload UI
  }, [entity]);

  return schedule;
}

/** Whether the tenant already has at least one saved database connection —
 * IS_DB_CONNECTED below is the one source of truth for this, read through
 * the useIsDbConnected() hook. Once true, the "Database Import" tab on
 * individual module pages is redundant with (and more confusing than) the
 * one connect-once-map-everything flow at Admin > Data Sources, which
 * already lists every remaining unmapped entity — so those per-page tabs
 * hide themselves rather than offering a second, scattered way to connect
 * a database.
 *
 * IS_DB_CONNECTED is a single module-level cache shared by every call site,
 * not a fetch-per-mount hook — every module page (Assets, Sensor Readings,
 * Inventory, Quality, Production, ...) renders its own `ConfigImportTabs`,
 * and each one used to independently call listSavedConnections() on mount,
 * so navigating between pages re-ran the same fetch and re-opened the same
 * "null while loading" window every single time (during which the
 * Database Import tab would flash visible before hiding again). Now the
 * first call anywhere warms the cache for the rest of the session, and every
 * later mount — on any page — reads the already-known answer instantly.
 *
 * Value is null only during that one-time initial fetch, so callers can
 * wait rather than briefly flashing the tab before hiding it. */
let IS_DB_CONNECTED: boolean | null = null;
let inFlightFetch: Promise<boolean> | null = null;
const dbConnectedListeners = new Set<(value: boolean | null) => void>();

function setIsDbConnected(value: boolean | null) {
  IS_DB_CONNECTED = value;
  dbConnectedListeners.forEach((listener) => listener(value));
}

function fetchIsDbConnected(): Promise<boolean> {
  if (!inFlightFetch) {
    inFlightFetch = listSavedConnections()
      .then((conns) => {
        const connected = conns.length > 0;
        setIsDbConnected(connected);
        return connected;
      })
      .catch(() => {
        // best-effort — a fetch failure shouldn't permanently hide the tab
        setIsDbConnected(false);
        return false;
      })
      .finally(() => {
        inFlightFetch = null;
      });
  }
  return inFlightFetch;
}

/** Call this the instant a database connection is successfully saved
 * (DatabaseImportWizard's handleTestConnection with save_as set, or
 * DataSourceSetup's handleConnect) — sets IS_DB_CONNECTED to true so every
 * already-mounted page's Database Import tab hides itself immediately,
 * instead of waiting for its next independent fetch (which, without this,
 * wouldn't happen until that page next remounts). */
export function markDatabaseConnected() {
  setIsDbConnected(true);
}

/** The reverse — call this when the tenant's saved connections drop to zero
 * (DataSourceSetup's handleDisconnect, the one place a connection can be
 * removed), so IS_DB_CONNECTED goes back to false and the Database Import
 * tab reappears everywhere immediately instead of staying hidden on stale
 * "still connected" state. */
export function markDatabaseDisconnected() {
  setIsDbConnected(false);
}

/** Reads the shared IS_DB_CONNECTED value — true once any database
 * connection is saved, false once we know there isn't one, null only
 * during the one-time initial check. See IS_DB_CONNECTED above for why
 * this isn't a plain fetch-on-mount hook. */
export function useIsDbConnected(): boolean | null {
  const [isDbConnected, setLocalIsDbConnected] = useState<boolean | null>(IS_DB_CONNECTED);

  useEffect(() => {
    const listener = (value: boolean | null) => setLocalIsDbConnected(value);
    dbConnectedListeners.add(listener);
    if (IS_DB_CONNECTED === null) {
      fetchIsDbConnected();
    }
    return () => {
      dbConnectedListeners.delete(listener);
    };
  }, []);

  return isDbConnected;
}

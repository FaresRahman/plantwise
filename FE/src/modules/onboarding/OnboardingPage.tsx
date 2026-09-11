import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronRight, Database, ListChecks, PenLine } from "lucide-react";

import { getOnboardingStatus, loadSampleData, markOnboardingComplete, OnboardingStepStatus } from "../../api/onboarding";
import { useAuth } from "../../auth/AuthContext";
import { useOnboardingStatus } from "../../auth/OnboardingContext";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { Spinner } from "../../components/Loading";
import { listSyncSchedules } from "../../api/dbImport";
import { DATABASE_ONBOARDING_STEPS, MANUAL_ONBOARDING_STEPS } from "./steps";

// "database_sync" is a frontend-only step (it renders <DataSourceSetup />)
// with no matching backend module, so it never appears in getOnboardingStatus's
// per-module list — it's done once at least one entity is mapped and syncing.
function stepIsComplete(key: string, status: OnboardingStepStatus[], syncedEntityCount: number): boolean {
  if (key === "database_sync") return syncedEntityCount > 0;
  return status.find((s) => s.module === key)?.complete ?? false;
}

// Same icon set every module page uses (via PageHeader/ModuleIcon) so each
// step reads as that module, not as an anonymous form.
const STEP_ICON_NAME: Record<string, React.ComponentProps<typeof ModuleIcon>["name"]> = {
  predictive_maintenance: "maintenance",
  production: "production",
  inventory: "inventory",
  quality: "quality",
  sop: "sop",
  shift_reports: "shift",
  invite_team: "invite",
  database_sync: "database",
};

type DataSourcePath = "database" | "manual";
// Keyed per tenant — a stale choice from a previously tested account in the
// same browser must never bleed into a different tenant's first login.
const PATH_STORAGE_PREFIX = "pw_onboarding_path_";

export default function OnboardingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { refresh: refreshOnboardingComplete } = useOnboardingStatus();
  const storageKey = `${PATH_STORAGE_PREFIX}${user?.tenant_id ?? "anon"}`;
  const [status, setStatus] = useState<OnboardingStepStatus[]>([]);
  const [syncedEntityCount, setSyncedEntityCount] = useState(0);
  const [path, setPath] = useState<DataSourcePath | null>(() => {
    const stored = localStorage.getItem(storageKey);
    return stored === "database" || stored === "manual" ? stored : null;
  });
  const [stepIndex, setStepIndex] = useState(0);
  // True from mount until the first status fetch resolves and stepIndex has
  // been corrected to wherever the user left off — avoids briefly rendering
  // step 1 (or a step the user already finished) before jumping.
  const [resolvingInitialStep, setResolvingInitialStep] = useState(() => path !== null);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [hoveredChip, setHoveredChip] = useState<number | null>(null);

  const ONBOARDING_STEPS = path === "database" ? DATABASE_ONBOARDING_STEPS : MANUAL_ONBOARDING_STEPS;

  function choosePath(next: DataSourcePath) {
    localStorage.setItem(storageKey, next);
    setPath(next);
    setStepIndex(0);
  }

  function changePath() {
    localStorage.removeItem(storageKey);
    setPath(null);
    setStepIndex(0);
  }

  useEffect(() => {
    if (!path) {
      setResolvingInitialStep(false);
      return;
    }
    setResolvingInitialStep(true);
    Promise.all([getOnboardingStatus(), path === "database" ? listSyncSchedules() : Promise.resolve([])]).then(
      ([s, schedules]) => {
        setStatus(s);
        setSyncedEntityCount(schedules.length);
        // Resume wherever the user left off, instead of always starting at
        // step 1 — jump to the first module that isn't complete yet.
        const firstIncomplete = ONBOARDING_STEPS.findIndex(
          (st) => !stepIsComplete(st.key, s, schedules.length)
        );
        if (firstIncomplete >= 0) setStepIndex(firstIncomplete);
        setResolvingInitialStep(false);
      }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  // Refresh completion status after each step so chip badges update in real time
  async function refreshStatus() {
    try {
      const [s, schedules] = await Promise.all([
        getOnboardingStatus(),
        path === "database" ? listSyncSchedules() : Promise.resolve([]),
      ]);
      setStatus(s);
      setSyncedEntityCount(schedules.length);
    } catch {
      /* ignore — network hiccup shouldn't lock the wizard */
    }
  }

  // Auto-refresh on every step change instead of requiring a manual button —
  // covers data loaded elsewhere (another tab, a teammate) since the wizard
  // has no other trigger to notice that.
  useEffect(() => {
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex]);

  async function handleFinish() {
    setFinishing(true);
    setFinishError(null);
    try {
      await markOnboardingComplete();
      // Update the shared onboarding-complete flag before navigating so
      // RequireOnboarding sees "complete" immediately on "/" instead of
      // bouncing back here on its next (still-stale) check.
      await refreshOnboardingComplete();
      navigate("/", { replace: true });
    } catch {
      setFinishError("Couldn't finish setup — check your connection and try again.");
    } finally {
      setFinishing(false);
    }
  }

  const isLast = stepIndex === ONBOARDING_STEPS.length - 1;
  const StepComponent = ONBOARDING_STEPS[stepIndex].component;

  function canJumpTo(idx: number): boolean {
    // Always allow jumping to completed steps or the current one
    if (idx <= stepIndex) return true;
    // Allow jumping to the immediate next step only if current is complete
    if (idx === stepIndex + 1) {
      return stepIsComplete(ONBOARDING_STEPS[stepIndex].key, status, syncedEntityCount);
    }
    return false;
  }

  if (path && resolvingInitialStep) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 80 }}>
        <Spinner size={28} />
      </div>
    );
  }

  if (!path) {
    const databasePoints = [
      "Assets, production lines, items, and shift schedules come in automatically",
      "Sensor readings and maintenance history stay synced every 5 minutes, all day",
      "Quality inspections and inventory movements sync too, no daily uploads needed",
      "You can still add a one-off entry by hand any time, for a correction or an exception",
    ];
    const manualPoints = [
      "Add assets, lines, items, and schedules with a quick form or a CSV upload",
      "Log sensor readings and maintenance visits yourself, whenever they happen",
      "Track quality inspections and inventory movements the same way",
      "Works with no database at all, and you can turn on database sync later from Admin",
    ];
    return (
      <div style={{ maxWidth: 1080 }}>
        <PageHeader
          icon={<ListChecks size={21} strokeWidth={1.8} />}
          title="Set up your plant"
          subtitle="First, how do you want to get your data in?"
        />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <button
            onClick={() => choosePath("database")}
            className="pw-plate surface"
            style={{ textAlign: "left", padding: 28, cursor: "pointer", border: "1.5px solid var(--color-accent-500)", position: "relative", display: "flex", flexDirection: "column" }}
          >
            <span
              style={{
                position: "absolute", top: 20, right: 20, fontSize: 10.5, fontWeight: 800, letterSpacing: ".04em", textTransform: "uppercase",
                background: "var(--color-accent-600)", color: "var(--color-accent-ink)", padding: "3px 9px", borderRadius: "var(--radius-full)",
              }}
            >
              Recommended
            </span>
            <div style={{ width: 44, height: 44, borderRadius: "var(--radius-md)", background: "var(--color-accent-100)", color: "var(--color-accent-800)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
              <Database size={21} strokeWidth={1.8} />
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>Automate with Database Sync</div>
            <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: "0 0 16px" }}>
              Connect your plant's database once. Every module below pulls its data straight from it, and stays current
              with no further work from you.
            </p>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {databasePoints.map((point) => (
                <li key={point} style={{ display: "flex", gap: 9, fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  <Check size={15} strokeWidth={2.5} style={{ flex: "none", marginTop: 2, color: "var(--color-accent-700)" }} />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </button>

          <button
            onClick={() => choosePath("manual")}
            className="pw-plate surface"
            style={{ textAlign: "left", padding: 28, cursor: "pointer", display: "flex", flexDirection: "column" }}
          >
            <div style={{ width: 44, height: 44, borderRadius: "var(--radius-md)", background: "var(--color-neutral-100)", color: "var(--color-text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
              <PenLine size={21} strokeWidth={1.8} />
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>Enter Data Manually</div>
            <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: "0 0 16px" }}>
              No database connection needed. Add each module's data yourself, at your own pace, using a quick form or a
              CSV upload.
            </p>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {manualPoints.map((point) => (
                <li key={point} style={{ display: "flex", gap: 9, fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                  <Check size={15} strokeWidth={2.5} style={{ flex: "none", marginTop: 2, color: "var(--color-text-tertiary)" }} />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1080 }}>
      <PageHeader
        icon={<ListChecks size={21} strokeWidth={1.8} />}
        title="Set up your plant"
        subtitle={path === "database" ? "Connect your database, then invite your team." : "Complete each module below, then invite your team."}
        actions={
          <button
            className="btn-secondary"
            style={{
              fontSize: 13,
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              background: "transparent",
              border: "1.5px solid var(--color-accent-600)",
              color: "var(--color-accent-700)",
            }}
            onClick={changePath}
          >
            <Database size={14} strokeWidth={2} color="var(--color-accent-700)" />
            Change data source
          </button>
        }
      />

      {/* --- Step chips --- */}
      <div style={{ display: "flex", gap: 8, marginBottom: 13, flexWrap: "wrap" }}>
        {ONBOARDING_STEPS.map((s, i) => {
          const complete = stepIsComplete(s.key, status, syncedEntityCount);
          const isCurrent = i === stepIndex;
          const isClickable = canJumpTo(i);
          const hovered = isClickable && hoveredChip === i;

          // Chip visual state — the current step gets the app's one signature
          // accent color (not a grayscale tint) so it reads as "you are here"
          // at a glance, including in dark mode. Completed steps stay neutral
          // (checkmark only, no color fill) so "current" is the only chip
          // that draws the eye.
          let chipBg = "transparent";
          let chipColor = "var(--color-text-secondary)";
          let chipBorder = "1px solid var(--color-border-default)";

          if (complete) {
            chipBg = hovered ? "var(--color-neutral-100)" : "var(--color-neutral-50)";
            chipColor = "var(--color-text-primary)";
            chipBorder = "1px solid var(--color-border-default)";
          } else if (isCurrent) {
            chipBg = hovered ? "var(--color-accent-200)" : "var(--color-accent-100)";
            chipColor = "var(--color-accent-900)";
            chipBorder = "1px solid var(--color-accent-400)";
          } else if (hovered) {
            chipBg = "var(--color-neutral-50)";
            chipBorder = "1px solid var(--color-border-strong)";
          }

          return (
            <button
              key={s.key}
              onClick={() => {
                if (canJumpTo(i)) {
                  setStepIndex(i);
                }
              }}
              onMouseEnter={() => setHoveredChip(i)}
              onMouseLeave={() => setHoveredChip((h) => (h === i ? null : h))}
              disabled={!isClickable}
              style={{
                fontSize: 12.5,
                padding: "6px 12px",
                borderRadius: "var(--radius-full)",
                fontWeight: isCurrent || complete ? 700 : 500,
                background: chipBg,
                color: chipColor,
                border: chipBorder,
                boxShadow: hovered ? "var(--shadow-xs)" : "none",
                cursor: isClickable ? "pointer" : "not-allowed",
                opacity: isClickable || complete ? 1 : 0.5,
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                fontFamily: "inherit",
                transition: "background var(--transition-fast), border-color var(--transition-fast), opacity var(--transition-fast), box-shadow var(--transition-fast)",
              }}
            >
              {complete && <Check size={13} strokeWidth={2.5} />}
              {s.title}
            </button>
          );
        })}
      </div>

      {/* --- Step content --- */}
      {/* No outline border — the card reads as a distinct surface via a
          tinted fill against the (white / near-black) page background
          instead, one step lighter/darker than the quick-add zone inside it
          so the layering is color, not lines. */}
      <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--radius-xl)", boxShadow: "var(--shadow-sm)", padding: 22, marginBottom: 13 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 18,
            paddingBottom: 16,
            borderBottom: "1px solid var(--color-border-default)",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 9,
                background: "var(--color-accent-100)",
                color: "var(--color-accent-800)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flex: "none",
              }}
            >
              <ModuleIcon name={STEP_ICON_NAME[ONBOARDING_STEPS[stepIndex].key] ?? "maintenance"} />
            </div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{ONBOARDING_STEPS[stepIndex].title}</h3>
          </div>
          <button
            className="btn-secondary"
            style={{ fontSize: 13, padding: "8px 16px" }}
            title="Populates every module with sample data at once (handy if you skipped past this earlier)"
            onClick={async () => {
              try {
                await loadSampleData();
                await refreshStatus();
              } catch {
                /* ignore — per-module fallback available */
              }
            }}
          >
            Load all sample data
          </button>
        </div>
        <StepComponent key={stepIndex} onDataLoaded={refreshStatus} />
      </div>

      {/* --- Navigation --- */}
      {/* No "Back": the step chips above already jump to any completed or
          current step, and leaving the wizard entirely is the browser's own
          back button's job. Status refreshes automatically on step change
          (see the effect above), so no manual "Refresh status" button either. */}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12 }}>
        {isLast ? (
          <>
            {finishError && (
              <span style={{ fontSize: 12.5, color: "var(--color-error-700)" }}>{finishError}</span>
            )}
            <button className="btn-primary" onClick={handleFinish} disabled={finishing}>
              {finishing ? "Finishing..." : "Finish"}
            </button>
          </>
        ) : (
          <button
            className="btn-primary"
            onClick={() => setStepIndex((i) => Math.min(ONBOARDING_STEPS.length - 1, i + 1))}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            Next
            <ChevronRight size={15} strokeWidth={2} />
          </button>
        )}
      </div>
    </div>
  );
}

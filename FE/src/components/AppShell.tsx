import React from "react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BadgeCheck,
  BookOpen,
  Boxes,
  ClipboardList,
  Copyright,
  Factory,
  LayoutDashboard,
  Lock,
  LogOut,
  MessageSquare,
  Moon,
  ShieldCheck,
  Sun,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { getDashboardSummary } from "../api/dashboard";
import { NAV_GROUP_ORDER, NAV_ITEMS } from "../app/nav";
import { applyTheme, resolveInitialTheme, type ThemeMode } from "../app/theme";
import { useAuth } from "../auth/AuthContext";
import { useOnboardingStatus } from "../auth/OnboardingContext";

function initialsOf(name: string | undefined): string {
  if (!name) return "U";
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "U";
}

/** One icon per nav item, keyed by its 2-letter monogram code (nav.ts is
 * append-only and intentionally has no React/icon dependency of its own). */
const NAV_ICON: Record<string, LucideIcon> = {
  DB: LayoutDashboard,
  AI: MessageSquare,
  PM: Wrench,
  PR: Factory,
  IN: Boxes,
  QA: BadgeCheck,
  SO: BookOpen,
  SR: ClipboardList,
  AD: ShieldCheck,
};

/**
 * App shell: a dark control-panel "chrome" (sidebar + topbar accent) framing
 * a light workspace. Active nav items get a small illuminated indicator
 * lamp rather than just a fill change, echoing a physical panel's switch
 * bank. Role-locked items (e.g. Admin for non-admins) are omitted entirely
 * rather than shown dimmed — the sidebar itself must not advertise them.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [staleCount, setStaleCount] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(() => resolveInitialTheme());
  const { complete: onboardingComplete } = useOnboardingStatus();
  // Only lock the nav once we positively know onboarding is incomplete —
  // treat "still loading" (null) the same as "done" so the sidebar doesn't
  // flash locked-then-unlocked on every page load.
  const onboardingLocked = onboardingComplete === false;
  const contentRef = useRef<HTMLDivElement>(null);

  function toggleTheme() {
    const next: ThemeMode = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  }

  useEffect(() => {
    getDashboardSummary()
      .then((summaries) =>
        // A module with no data uploaded yet (last_updated_at === null) has
        // never been configured — that's a gap, not staleness (same "gap,
        // not a zero" distinction FreshnessBadge already makes per-card).
        // is_stale defaults to true for that case on the backend (a chatbot
        // safety default: "if data isn't there, treat it as not current"),
        // but surfacing that in this plantwide count reads as an alarm
        // about a brand-new tenant that hasn't touched a module yet.
        setStaleCount(summaries.filter((s) => s.is_stale && s.last_updated_at != null).length)
      )
      .catch(() => setStaleCount(0));
  }, []);

  // Every module page is long; without this, navigating to a new page via
  // the sidebar keeps whatever scroll position the previous page was at,
  // landing the reader mid-content instead of at the top.
  useEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [location.pathname]);

  const activeItem = NAV_ITEMS.find((item) => item.path === location.pathname);
  const screenTitle = activeItem?.label ?? "Plantwise";

  const showRoleBanner = user?.role === "viewer" || user?.role === "operator";
  const roleBanner =
    user?.role === "viewer"
      ? {
          text: "Viewer role: read-only. You can view the dashboard, shift reports and the assistant, but not enter data or change configuration.",
          bg: "var(--color-neutral-100)",
          fg: "var(--color-neutral-700)",
          border: "var(--color-border-default)",
        }
      : {
          text: "Operator role: you can enter data (forms + CSV) and action recommendations. Configuration is Admin-only.",
          bg: "var(--color-info-50)",
          fg: "var(--color-info-800)",
          border: "var(--color-info-200)",
        };

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* sidebar */}
      <div
        className="chrome-sidebar chrome-scroll"
        style={{
          width: 248,
          flex: "none",
          background: "var(--color-chrome-950)",
          borderRight: "1px solid var(--color-chrome-950)",
          height: "100vh",
          position: "sticky",
          top: 0,
          overflow: "auto",
          padding: "18px 12px",
          display: "flex",
          flexDirection: "column",
          transition: "width var(--transition-base)",
        }}
      >
        <Link
          to="/"
          className="brand"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "4px 6px 18px",
            marginBottom: 6,
            borderBottom: "1px solid var(--color-chrome-border)",
            textDecoration: "none",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              flex: "none",
              background: "var(--color-accent-600)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--color-accent-ink)",
              fontWeight: 800,
              fontSize: 15,
              fontFamily: "var(--font-family-display)",
              clipPath: "polygon(18% 0, 100% 0, 100% 82%, 82% 100%, 0 100%, 0 18%)",
            }}
          >
            P
          </div>
          <div className="chrome-wordmark" style={{ minWidth: 0 }}>
            <div style={{ fontFamily: "var(--font-family-display)", fontWeight: 600, fontSize: 15.5, lineHeight: 1.1, color: "var(--color-chrome-text-active)" }}>
              Plantwise
            </div>
            <div className="chrome-sub table-cell-truncate" style={{ fontSize: 11, color: "var(--color-chrome-text-muted)", maxWidth: 160 }}>
              {user?.email}
            </div>
          </div>
        </Link>

        {NAV_GROUP_ORDER.map((group) => {
          const groupItems = NAV_ITEMS.filter((item) => item.group === group && item.roles.includes(user?.role ?? "viewer"));
          if (groupItems.length === 0) return null;
          return (
            <div key={group} style={{ marginBottom: 10 }}>
              <div
                className="nav-group-label"
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: ".09em",
                  textTransform: "uppercase",
                  color: "var(--color-chrome-text-muted)",
                  padding: "6px 10px",
                }}
              >
                {group}
              </div>
              {groupItems.map((item) => {
                const active = location.pathname === item.path;
                const locked = onboardingLocked;
                const Icon = NAV_ICON[item.mono] ?? LayoutDashboard;
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className="nav-item"
                    onClick={onboardingLocked ? (e) => e.preventDefault() : undefined}
                    aria-disabled={locked || undefined}
                    title={onboardingLocked ? "Complete onboarding to access this" : undefined}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      borderRadius: "999px",
                      cursor: onboardingLocked ? "not-allowed" : "pointer",
                      background: active ? "var(--color-accent-600)" : "transparent",
                      marginBottom: 1,
                      textDecoration: "none",
                      opacity: locked ? 0.45 : 1,
                    }}
                  >
                    <Icon size={16} strokeWidth={1.8} color={active ? "var(--color-accent-ink)" : "var(--color-chrome-text)"} />
                    <span
                      className="nav-item-label"
                      style={{
                        fontSize: 13.5,
                        fontWeight: active ? 700 : 500,
                        color: active ? "var(--color-accent-ink)" : "var(--color-chrome-text)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {item.label}
                    </span>
                    {onboardingLocked && (
                      <Lock size={11} strokeWidth={2} style={{ marginLeft: "auto", color: "var(--color-chrome-text-muted)" }} />
                    )}
                  </Link>
                );
              })}
            </div>
          );
        })}

        {onboardingLocked && (
          <p style={{ fontSize: 11.5, color: "var(--color-chrome-text-muted)", margin: "4px 6px 0", lineHeight: 1.5 }}>
            Complete onboarding to access these features.
          </p>
        )}

        <div
          className="chrome-label"
          style={{
            marginTop: "auto",
            paddingTop: 14,
            borderTop: "1px solid var(--color-chrome-border)",
            fontSize: 11,
            color: "var(--color-chrome-text-muted)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          <Copyright size={12} strokeWidth={1.8} />
          {new Date().getFullYear()} Soft Suave
        </div>
      </div>

      {/* main */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {/* topbar */}
        <div
          style={{
            height: 60,
            flex: "none",
            borderBottom: "1px solid var(--color-border-default)",
            background: "var(--color-surface-default)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 24px",
            position: "sticky",
            top: 0,
            zIndex: 15,
          }}
        >
          <div style={{ fontSize: 19, fontFamily: "var(--font-family-display)", fontWeight: 800, letterSpacing: "-.015em" }}>{screenTitle}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {staleCount > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, fontWeight: 600, color: "var(--color-warning-700)" }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--color-warning-500)" }} />
                {staleCount} module{staleCount > 1 ? "s" : ""} stale
              </div>
            )}
            <button
              onClick={toggleTheme}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 32,
                height: 32,
                border: "1px solid var(--color-border-default)",
                borderRadius: "50%",
                background: "none",
                cursor: "pointer",
                flex: "none",
              }}
            >
              {theme === "dark" ? (
                <Sun size={15} strokeWidth={1.8} color="var(--color-accent-600)" />
              ) : (
                <Moon size={15} strokeWidth={1.8} color="var(--color-info-600)" />
              )}
            </button>
            <div style={{ position: "relative" }}>
              <div
                onClick={() => setMenuOpen((v) => !v)}
                title={user?.full_name ?? "Account"}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "5px 10px",
                  border: "1px solid var(--color-border-default)",
                  borderRadius: 9999,
                  cursor: "pointer",
                  background: menuOpen ? "var(--color-neutral-50)" : "transparent",
                }}
              >
                <span
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: "50%",
                    background: "var(--color-fill-solid)",
                    color: "var(--color-fill-solid-fg)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 12,
                    fontWeight: 800,
                  }}
                >
                  {initialsOf(user?.full_name)}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, textTransform: "capitalize" }}>{user?.role}</span>
              </div>

              {menuOpen && (
                <>
                  <div style={{ position: "fixed", inset: 0, zIndex: 19 }} onClick={() => setMenuOpen(false)} />
                  <div
                    className="surface"
                    style={{
                      position: "absolute",
                      right: 0,
                      top: "calc(100% + 8px)",
                      width: 220,
                      zIndex: 20,
                      boxShadow: "var(--shadow-lg)",
                      padding: 6,
                    }}
                  >
                    <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--color-border-subtle)", marginBottom: 4 }}>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{user?.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>{user?.email}</div>
                    </div>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        logout();
                        navigate("/login", { replace: true });
                      }}
                      className="btn-ghost"
                      style={{ width: "100%", textAlign: "left", color: "var(--color-error-700)", display: "flex", alignItems: "center", gap: 8 }}
                    >
                      <LogOut size={14} strokeWidth={1.8} />
                      Sign out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {showRoleBanner && (
          <div
            style={{
              background: roleBanner.bg,
              borderBottom: `1px solid ${roleBanner.border}`,
              padding: "9px 24px",
              fontSize: 13,
              color: roleBanner.fg,
              fontWeight: 600,
            }}
          >
            {roleBanner.text}
          </div>
        )}

        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <div ref={contentRef} className="pw-scroll" style={{ flex: 1, minWidth: 0, overflow: "auto", padding: 24 }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

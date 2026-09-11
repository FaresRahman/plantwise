import React from "react";
import { Navigate } from "react-router-dom";

import { Spinner } from "../components/Loading";
import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading)
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <Spinner size={32} />
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;

  return <>{children}</>;
}

/**
 * Wrap page content that only some roles should see, e.g.:
 *   <RoleGuard allow={["admin"]}><AssetRegistryForm /></RoleGuard>
 * Viewers get the same routes as everyone (read-only dashboard per PRD) —
 * use this for the config/action affordances, not for hiding whole pages.
 */
export function RoleGuard({ allow, children }: { allow: Array<"admin" | "operator" | "viewer">; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !allow.includes(user.role)) return null;
  return <>{children}</>;
}

/**
 * Wrap a whole route (not just a page affordance) that only some roles
 * should ever reach — by nav click, typed URL, or browser Back. Unlike
 * RoleGuard (which renders nothing), this redirects home, since a bare
 * blank screen behind the AppShell chrome reads as broken, not "not for you".
 */
export function RequireRole({ allow, children }: { allow: Array<"admin" | "operator" | "viewer">; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !allow.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

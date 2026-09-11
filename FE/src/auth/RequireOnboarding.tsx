import React from "react";
import { Navigate } from "react-router-dom";

import { Spinner } from "../components/Loading";
import { useOnboardingStatus } from "./OnboardingContext";

/**
 * Wrap any protected route that shouldn't be reachable — by nav click, typed
 * URL, or browser Back — until the tenant finishes onboarding. `/onboarding`
 * itself is deliberately NOT wrapped in this, so an incomplete-onboarding
 * user can actually reach the wizard.
 */
export function RequireOnboarding({ children }: { children: React.ReactNode }) {
  const { complete, loading } = useOnboardingStatus();

  if (loading)
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <Spinner size={32} />
      </div>
    );
  if (complete === false) return <Navigate to="/onboarding" replace />;

  return <>{children}</>;
}

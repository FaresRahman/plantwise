import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

import { isOnboardingComplete } from "../api/onboarding";
import { useAuth } from "./AuthContext";

interface OnboardingState {
  /** null until the first check resolves (or while logged out) */
  complete: boolean | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingState | undefined>(undefined);

/**
 * Single shared source of truth for "has this tenant finished the setup
 * wizard?". AppShell used to fetch this itself on every mount — and it
 * remounts on every route change (see routes.tsx's <Protected>) — so the
 * same check was refetched on every navigation with nothing to coordinate
 * it against RequireOnboarding's own check. This fetches once per
 * login/logout instead, and exposes refresh() for callers (onboarding
 * finishing) that need the rest of the app to see the new state immediately.
 */
export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [complete, setComplete] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!user) {
      setComplete(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await isOnboardingComplete();
      setComplete(res.complete);
    } catch {
      // Can't reach the API — don't lock the whole app over a network hiccup.
      setComplete(true);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return; // wait for the initial session check to land first
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user?.id]);

  return (
    <OnboardingContext.Provider value={{ complete, loading: authLoading || loading, refresh }}>
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboardingStatus(): OnboardingState {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboardingStatus must be used within OnboardingProvider");
  return ctx;
}

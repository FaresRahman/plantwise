import React from "react";
import { Route, Routes } from "react-router-dom";

import AcceptInvitePage from "../auth/AcceptInvitePage";
import { useAuth } from "../auth/AuthContext";
import LoginPage from "../auth/LoginPage";
import { ProtectedRoute, RequireRole } from "../auth/ProtectedRoute";
import { RequireOnboarding } from "../auth/RequireOnboarding";
import SignupPage from "../auth/SignupPage";
import VerifyEmailPage from "../auth/VerifyEmailPage";
import { AppShell } from "../components/AppShell";
import AdminPage from "../modules/admin/AdminPage";
import ChatbotPage from "../modules/chatbot/ChatbotPage";
import DashboardPage from "../modules/dashboard/DashboardPage";
import InventoryPage from "../modules/inventory/InventoryPage";
import OnboardingPage from "../modules/onboarding/OnboardingPage";
import PredictiveMaintenancePage from "../modules/predictive-maintenance/PredictiveMaintenancePage";
import ProductionPage from "../modules/production/ProductionPage";
import QualityPage from "../modules/quality/QualityPage";
import ShiftReportsPage from "../modules/shift-reports/ShiftReportsPage";
import SopPage from "../modules/sop/SopPage";
import LandingPage from "../public/LandingPage";

function Protected({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <RequireOnboarding>
        <AppShell>{children}</AppShell>
      </RequireOnboarding>
    </ProtectedRoute>
  );
}

/** The onboarding wizard is auth-gated like everything else, but must NOT
 * go through RequireOnboarding — that's the guard that sends incomplete
 * tenants here in the first place. */
function ProtectedOnboarding({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}

/** "/" is public marketing (LandingPage) for logged-out visitors and the
 * real Dashboard for logged-in users — not a redirect-to-login like every
 * other protected route, since a landing page needs to be visible without
 * an account. */
function Root() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <LandingPage />;
  return (
    <RequireOnboarding>
      <AppShell>
        <DashboardPage />
      </AppShell>
    </RequireOnboarding>
  );
}

/**
 * Central route table — APPEND-ONLY. Add your module's <Route> at the end
 * of the protected block; don't restructure this file. See DEV_BRIEF
 * section 4.6.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/verify" element={<VerifyEmailPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />

      <Route path="/" element={<Root />} />

      {/* --- Dev A --- */}
      <Route path="/predictive-maintenance" element={<Protected><PredictiveMaintenancePage /></Protected>} />
      <Route path="/production" element={<Protected><ProductionPage /></Protected>} />
      <Route path="/inventory" element={<Protected><InventoryPage /></Protected>} />
      <Route path="/quality" element={<Protected><QualityPage /></Protected>} />

      {/* --- Dev B --- */}
      <Route path="/sop" element={<Protected><SopPage /></Protected>} />
      <Route path="/shift-reports" element={<Protected><ShiftReportsPage /></Protected>} />
      <Route path="/chat" element={<Protected><ChatbotPage /></Protected>} />
      <Route
        path="/admin"
        element={
          <Protected>
            <RequireRole allow={["admin"]}>
              <AdminPage />
            </RequireRole>
          </Protected>
        }
      />
      <Route path="/onboarding" element={<ProtectedOnboarding><OnboardingPage /></ProtectedOnboarding>} />
    </Routes>
  );
}

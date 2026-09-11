import React, { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { useAuth } from "./AuthContext";
import { BrandMark } from "./AuthNotice";

export default function LoginPage() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [submitting, setSubmitting] = useState(false);
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const nextFieldErrors: { email?: string; password?: string } = {};
    if (!email.trim()) nextFieldErrors.email = "Enter your email address.";
    if (!password) nextFieldErrors.password = "Enter your password.";
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) return;

    setSubmitting(true);
    try {
      await login(email, password);
      // Always land on "/" — whether that's the dashboard or a redirect to
      // the onboarding wizard is RequireOnboarding's call, not this page's.
      // (This used to re-check onboarding status here too, but only routed
      // to the wizard when *no* module had any data yet, which skipped
      // users who were already partway through onboarding.)
      setRedirectTo("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  // Post-login redirect — single navigation mechanism so the login page
  // is reliably replaced in history.  Back button from the dashboard
  // will never land on /login again.
  if (redirectTo) return <Navigate to={redirectTo} replace />;

  // Already signed in (e.g. the browser's Back button landed here after a
  // successful login) — replace this history entry instead of showing the
  // form again, so Back/Forward can't get stuck bouncing on /login.
  if (user) return <Navigate to="/" replace />;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "minmax(0, 5fr) minmax(0, 6fr)",
      }}
    >
      {/* decorative brand panel — echoes the landing-page hero treatment
          (radial highlight + diagonal hairline texture over a dark chrome
          gradient) and the same dark/light split SignupPage uses, so the
          login screen reads as part of the same system instead of a bare
          card floating on a flat tint. Purely decorative: no marketing copy
          duplicated here, just brand identity. */}
      <div
        style={{
          position: "relative",
          overflow: "hidden",
          background:
            "radial-gradient(70% 55% at 30% 20%, rgba(245,197,24,.10), transparent 60%)," +
            "repeating-linear-gradient(115deg, rgba(255,255,255,.035) 0 2px, transparent 2px 46px)," +
            "linear-gradient(165deg, var(--color-chrome-700), var(--color-chrome-950) 70%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <BrandMark />
          <div style={{ fontFamily: "var(--font-family-display)", fontWeight: 600, fontSize: 17, color: "var(--color-chrome-text-active)" }}>
            Plantwise
          </div>
        </div>
      </div>

      {/* form panel */}
      <div
        style={{
          background: "var(--color-neutral-50)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "48px 24px",
        }}
      >
        <div style={{ width: "100%", maxWidth: 420 }}>
          <h1 style={{ fontSize: 22, margin: "0 0 6px", textAlign: "center" }}>Welcome back</h1>
          <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", margin: "0 0 24px", textAlign: "center" }}>
            Log in to your plant's workspace.
          </p>

          <form onSubmit={handleSubmit} noValidate className="surface" style={{ padding: 26, display: "flex", flexDirection: "column", gap: 14 }}>
            <label style={{ fontSize: 13, fontWeight: 600 }}>
              Email
              <input
                className="input"
                style={{ marginTop: 6, borderColor: fieldErrors.email ? "var(--color-error-500)" : undefined }}
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }));
                }}
              />
              {fieldErrors.email && (
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-error-600)", marginTop: 5 }}>{fieldErrors.email}</div>
              )}
            </label>
            <label style={{ fontSize: 13, fontWeight: 600 }}>
              Password
              <input
                className="input"
                style={{ marginTop: 6, borderColor: fieldErrors.password ? "var(--color-error-500)" : undefined }}
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }));
                }}
              />
              {fieldErrors.password && (
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-error-600)", marginTop: 5 }}>{fieldErrors.password}</div>
              )}
            </label>

            {error && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  background: "var(--color-error-50)",
                  border: "1px solid var(--color-error-100)",
                  borderLeft: "3px solid var(--color-error-600)",
                  borderRadius: "var(--radius-lg)",
                  padding: "10px 12px",
                  color: "var(--color-error-700)",
                  fontSize: 13,
                }}
              >
                <AlertTriangle size={14} strokeWidth={2} style={{ flex: "none", marginTop: 1 }} />
                <span>{error}</span>
              </div>
            )}

            <button className="btn-primary" type="submit" disabled={submitting} style={{ padding: 13, fontSize: 15 }}>
              {submitting ? "Signing in..." : "Log In"}
            </button>

            <div style={{ height: 1, background: "var(--color-border-default)", margin: "4px 0" }} />

            <button
              type="button"
              disabled
              style={{
                border: "1px solid var(--color-border-default)",
                background: "var(--color-neutral-50)",
                color: "var(--color-text-tertiary)",
                font: "inherit",
                fontSize: 14,
                fontWeight: 600,
                padding: 11,
                borderRadius: "var(--radius-lg)",
                cursor: "not-allowed",
              }}
            >
              Single Sign-On (coming in Phase 2)
            </button>

            <div style={{ textAlign: "center", fontSize: 13, color: "var(--color-text-secondary)" }}>
              New here?{" "}
              <Link to="/signup" style={{ color: "var(--color-primary-700)", fontWeight: 700 }}>
                Create an account
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

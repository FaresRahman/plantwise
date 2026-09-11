import React, { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { acceptInvite } from "../api/auth";
import { useAuth } from "./AuthContext";
import { AuthNotice, BrandMark } from "./AuthNotice";

export default function AcceptInvitePage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  // Already signed in — redirect to the app.
  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!password) {
      setPasswordError("Enter a password.");
      return;
    }
    setPasswordError(null);
    const token = params.get("token");
    if (!token) {
      setError("Missing invite token");
      return;
    }
    setSubmitting(true);
    try {
      await acceptInvite({ token, password });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept invite");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <AuthNotice
        icon={<CheckCircle2 size={28} strokeWidth={1.8} />}
        iconTone="success"
        title="Password created"
        action={
          <Link to="/login" className="btn-primary" style={{ padding: "13px 32px", fontSize: 15, textDecoration: "none" }}>
            Go to login
          </Link>
        }
      >
        Your account is ready. Log in with your email and new password.
      </AuthNotice>
    );
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-neutral-50)",
        padding: "48px 24px",
      }}
    >
      <div style={{ width: "100%", maxWidth: 420 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <BrandMark />
          <div
            style={{
              fontFamily: "var(--font-family-display)",
              fontWeight: 600,
              fontSize: 13,
              letterSpacing: ".08em",
              textTransform: "uppercase",
              color: "var(--color-text-tertiary)",
            }}
          >
            Plantwise
          </div>
        </div>

        <h1 style={{ fontSize: 26, margin: "0 0 8px", textAlign: "center" }}>You've been invited</h1>
        <p style={{ fontSize: 15, color: "var(--color-text-secondary)", margin: "0 0 28px", textAlign: "center" }}>
          Set a password to activate your Plantwise account.
        </p>

        <form onSubmit={handleSubmit} noValidate className="surface" style={{ padding: 26, display: "flex", flexDirection: "column", gap: 14 }}>
          <label style={{ fontSize: 13, fontWeight: 600 }}>
            New password
            <input
              className="input"
              style={{ marginTop: 6, borderColor: passwordError ? "var(--color-error-500)" : undefined }}
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (passwordError) setPasswordError(null);
              }}
            />
            {passwordError && (
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-error-600)", marginTop: 5 }}>{passwordError}</div>
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
            {submitting ? "Saving..." : "Set password & sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

import React, { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { CheckCircle2, Mail, AlertTriangle } from "lucide-react";

import { signup } from "../api/auth";
import { useAuth } from "./AuthContext";
import { AuthNotice, BrandMark } from "./AuthNotice";

const CHECKLIST = ["One plant per account (v1)", "Email + password (SSO coming later)", "Invite your team once you're in"];

export default function SignupPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ tenant_name: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const [done, setDone] = useState(false);
  const [autoVerified, setAutoVerified] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const nextFieldErrors: Partial<Record<keyof typeof form, string>> = {};
    if (!form.full_name.trim()) nextFieldErrors.full_name = "Enter your name.";
    if (!form.email.trim()) nextFieldErrors.email = "Enter your work email.";
    if (!form.tenant_name.trim()) nextFieldErrors.tenant_name = "Enter your plant's name.";
    if (!form.password) nextFieldErrors.password = "Choose a password.";
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) return;

    setSubmitting(true);
    try {
      const result = await signup(form);
      if (result.is_verified) {
        setAutoVerified(true);
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  // Already signed in — redirect to the app.
  if (user) return <Navigate to="/" replace />;

  if (done) {
    if (autoVerified) {
      return (
        <AuthNotice
          icon={<CheckCircle2 size={30} strokeWidth={1.8} />}
          iconTone="success"
          title="Account created"
          action={
            <button
              className="btn-primary"
              onClick={() => navigate("/login")}
              style={{ padding: "12px 32px", fontSize: 15, fontWeight: 700 }}
            >
              Go to sign in
            </button>
          }
        >
          Your account <strong style={{ color: "var(--color-text-primary)" }}>{form.email}</strong> is ready.
        </AuthNotice>
      );
    }

    return (
      <AuthNotice
        icon={<Mail size={28} strokeWidth={1.8} />}
        iconTone="primary"
        title="Check your email"
        action={
          <Link to="/login" style={{ color: "var(--color-primary-700)", fontWeight: 700, fontSize: 13 }}>
            Back to sign in
          </Link>
        }
      >
        We sent a verification link to <strong style={{ color: "var(--color-text-primary)" }}>{form.email}</strong>. Click it to
        confirm your account and create your tenant.
      </AuthNotice>
    );
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "minmax(0, 5fr) minmax(0, 6fr)",
      }}
    >
      {/* marketing / instrument panel side */}
      <div
        style={{
          background: "linear-gradient(180deg, var(--color-chrome-950), var(--color-chrome-800) 70%)",
          color: "var(--color-chrome-text)",
          padding: "56px 48px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: 28,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <BrandMark />
          <div style={{ fontFamily: "var(--font-family-display)", fontWeight: 600, fontSize: 17, color: "var(--color-chrome-text-active)" }}>
            Plantwise
          </div>
        </div>

        <div>
          <h1 style={{ fontSize: 26, letterSpacing: "-.02em", margin: "0 0 12px", color: "var(--color-chrome-text-active)" }}>
            Create your plant's account
          </h1>
          <p style={{ fontSize: 14, color: "var(--color-chrome-text)", lineHeight: 1.6, margin: 0, maxWidth: 400 }}>
            You'll sign up as the plant Admin and set up your six modules next.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {CHECKLIST.map((item) => (
            <div key={item} style={{ display: "flex", gap: 12, alignItems: "center", color: "var(--color-chrome-text)", fontSize: 14.5 }}>
              <span
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  background: "rgba(245, 197, 24, 0.16)",
                  color: "var(--color-chrome-led)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flex: "none",
                }}
              >
                <CheckCircle2 size={13} strokeWidth={2.5} />
              </span>
              {item}
            </div>
          ))}
        </div>
      </div>

      {/* form side */}
      <div
        style={{
          background: "var(--color-neutral-50)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "48px 32px",
        }}
      >
        <form
          onSubmit={handleSubmit}
          noValidate
          className="surface"
          style={{ width: "100%", maxWidth: 420, padding: 28, display: "flex", flexDirection: "column", gap: 14 }}
        >
          {(
            [
              { key: "full_name", label: "Your name", type: "text" },
              { key: "email", label: "Work email", type: "email" },
              { key: "tenant_name", label: "Plant name", type: "text" },
              { key: "password", label: "Password", type: "password" },
            ] as const
          ).map((f) => (
            <label key={f.key} style={{ fontSize: 13, fontWeight: 600 }}>
              {f.label}
              <input
                className="input"
                style={{ marginTop: 6, borderColor: fieldErrors[f.key] ? "var(--color-error-500)" : undefined }}
                type={f.type}
                value={form[f.key]}
                onChange={(e) => {
                  setForm({ ...form, [f.key]: e.target.value });
                  if (fieldErrors[f.key]) setFieldErrors((fe) => ({ ...fe, [f.key]: undefined }));
                }}
              />
              {fieldErrors[f.key] && (
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-error-600)", marginTop: 5 }}>{fieldErrors[f.key]}</div>
              )}
            </label>
          ))}

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

          <button className="btn-primary" type="submit" disabled={submitting} style={{ padding: 13, fontSize: 15, marginTop: 4 }}>
            {submitting ? "Creating account..." : "Create Account"}
          </button>
          <div style={{ textAlign: "center", fontSize: 13, color: "var(--color-text-secondary)" }}>
            Already have an account?{" "}
            <Link to="/login" style={{ color: "var(--color-primary-700)", fontWeight: 700 }}>
              Log in
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}

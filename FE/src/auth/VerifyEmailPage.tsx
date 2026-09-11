import React, { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Mail } from "lucide-react";

import { verifyEmail } from "../api/auth";
import { useAuth } from "./AuthContext";
import { AuthNotice } from "./AuthNotice";

export default function VerifyEmailPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const [status, setStatus] = useState<"pending" | "ok" | "error">("pending");

  // Already signed in — no need to verify anything.
  if (user) return <Navigate to="/" replace />;

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setStatus("error");
      return;
    }
    verifyEmail(token)
      .then(() => setStatus("ok"))
      .catch(() => setStatus("error"));
  }, [params]);

  if (status === "pending") {
    return (
      <AuthNotice icon={<Mail size={26} strokeWidth={1.8} />} iconTone="primary" title="Verifying your email" animate>
        One moment...
      </AuthNotice>
    );
  }

  if (status === "ok") {
    return (
      <AuthNotice
        icon={<CheckCircle2 size={28} strokeWidth={1.8} />}
        iconTone="success"
        title="Email verified"
        action={
          <Link to="/login" className="btn-primary" style={{ padding: "13px 28px", fontSize: 15, textDecoration: "none" }}>
            Sign in
          </Link>
        }
      >
        Your account is confirmed. Sign in to start setting up your plant.
      </AuthNotice>
    );
  }

  return (
    <AuthNotice
      icon={<AlertTriangle size={26} strokeWidth={1.8} />}
      iconTone="error"
      title="Link invalid or expired"
      action={
        <Link to="/signup" style={{ color: "var(--color-primary-700)", fontWeight: 700, fontSize: 13 }}>
          Back to sign up
        </Link>
      }
    >
      That verification link didn't work. Sign up again to get a new one, or contact your Admin if you were invited.
    </AuthNotice>
  );
}

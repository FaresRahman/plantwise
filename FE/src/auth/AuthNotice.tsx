import React from "react";

/** Chamfered-square brand mark — shared by every auth screen (login, signup,
 * verify, invite) so it's defined once instead of copy-pasted per page. */
export function BrandMark({ size = 40 }: { size?: number }) {
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        flex: "none",
        background: "var(--color-accent-600)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--color-accent-ink)",
        fontWeight: 800,
        fontSize: size * 0.45,
        fontFamily: "var(--font-family-display)",
        clipPath: "polygon(18% 0, 100% 0, 100% 82%, 82% 100%, 0 100%, 0 18%)",
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,.18)",
      }}
    >
      P
    </div>
  );
}

const TONE_BG: Record<string, string> = {
  primary: "var(--color-primary-50)",
  success: "var(--color-success-50)",
  error: "var(--color-error-50)",
};
const TONE_FG: Record<string, string> = {
  primary: "var(--color-primary-700)",
  success: "var(--color-success-600)",
  error: "var(--color-error-700)",
};

/**
 * Shared layout for every auth interstitial (check-your-email, account
 * created, email verified, invalid link, ...). Every *active* auth screen
 * (login, signup) already gets the branded split-panel + `.surface` card
 * treatment — these confirmation screens previously skipped both (bare
 * centered text on a flat background, no card, no brand mark), which read
 * as an unstyled placeholder next to the rest of the flow. This gives them
 * the same brand mark + card surface every other page already uses.
 */
export function AuthNotice({
  icon,
  iconTone = "primary",
  title,
  children,
  action,
  animate = false,
}: {
  icon: React.ReactNode;
  iconTone?: "primary" | "success" | "error";
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  animate?: boolean;
}) {
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
      {animate && (
        <style>{`
          @keyframes pw-pulse-ring {
            0% { box-shadow: 0 0 0 0 rgba(26, 26, 23, 0.2); }
            70% { box-shadow: 0 0 0 10px rgba(26, 26, 23, 0); }
            100% { box-shadow: 0 0 0 0 rgba(26, 26, 23, 0); }
          }
        `}</style>
      )}
      <div className="surface" style={{ width: "100%", maxWidth: 440, textAlign: "center", padding: "40px 32px" }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
          <BrandMark size={36} />
        </div>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 16,
            background: TONE_BG[iconTone],
            color: TONE_FG[iconTone],
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 22px",
            animation: animate ? "pw-pulse-ring 1.8s ease-out infinite" : "none",
          }}
        >
          {icon}
        </div>
        <h1 style={{ fontSize: 19, margin: "0 0 8px" }}>{title}</h1>
        {children && (
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: "0 0 22px" }}>
            {children}
          </div>
        )}
        {action}
      </div>
    </div>
  );
}

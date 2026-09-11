import React from "react";
import { useNavigate } from "react-router-dom";
import { Clock, LayoutDashboard, Lightbulb, Settings2, ShieldCheck, UploadCloud, UserPlus } from "lucide-react";

/** Matches the wireframe's "LANDING" screen exactly. Public/unauthenticated —
 * every CTA on this page routes to either /signup or /login since nothing
 * past this point is viewable without an account. Rendered at "/" when the
 * visitor isn't logged in (see routes.tsx's Root component); logged-in users
 * see the real Dashboard at the same path instead.
 *
 * Visual reference: Ferox — B2B Heavy Machinery Web Platform (Dribbble
 * 27033421) — floating pill navbar over a dark industrial hero, cut-corner
 * "tab" cards, a single golden-yellow accent spent sparingly against a
 * black/white base. See src/styles/theme.css for the token definitions.
 */

const PROBLEMS = [
  { title: "Reactive maintenance", desc: "Equipment gets fixed after it breaks, though the warning signs were already in the data." },
  { title: "Siloed data", desc: "Production, inventory, quality and maintenance each live in a different system or binder." },
  { title: "Tribal knowledge", desc: "Safe servicing know-how lives in unread SOPs and staff who eventually leave." },
  { title: "Backward reporting", desc: "Shift handovers are scribbled notes, clear only after the moment to act has passed." },
];

const MODULES = [
  { mono: "PM", title: "Predictive Maintenance", desc: "Asset registry + sensor readings → explainable failure recommendations." },
  { mono: "PR", title: "Production", desc: "Output vs plan, OEE, and downtime attributed by station and reason." },
  { mono: "IN", title: "Inventory", desc: "Run-out projection from consumption rate and low-stock flags." },
  { mono: "QA", title: "Quality", desc: "Defect-rate trends and root-cause hints from production events." },
  { mono: "SO", title: "SOP Library", desc: "Upload PDFs/DOCX, indexed for cited answers. Never a guess." },
  { mono: "SR", title: "Shift Reports", desc: "Auto-generated handovers with explicit next-shift actions." },
];

const STEPS = [
  { n: "1", title: "Sign up & verify", desc: "Create your account and confirm your email.", Icon: UserPlus },
  { n: "2", title: "Configure 6 modules", desc: "Fill a short form per module, or load sample data to start.", Icon: Settings2 },
  { n: "3", title: "Upload data", desc: "Drop in readings, output or stock as CSV/Excel, validated before commit.", Icon: UploadCloud },
  { n: "4", title: "Dashboard + alerts", desc: "The engine runs its first pass and surfaces recommendations.", Icon: LayoutDashboard },
];

const TRUST = [
  { title: "Freshness you can trust", desc: "Every card shows when its data last arrived. Stale data is flagged, never passed off as live.", Icon: Clock, accent: "var(--color-info-600)", tint: "var(--color-info-50)" },
  { title: "Explainable, not a black box", desc: "Recommendations come from transparent rules and trends, with the reasoning shown every time.", Icon: Lightbulb, accent: "var(--color-warning-600)", tint: "var(--color-warning-50)" },
  { title: "Strict tenant isolation", desc: "Data, documents and config are isolated per plant, with email-verified, role-based access.", Icon: ShieldCheck, accent: "var(--color-success-600)", tint: "var(--color-success-50)" },
];

/** The chamfered-corner brand mark used everywhere else in the app (see
 * AppShell.tsx's sidebar) — reused here, same colors, so the marketing
 * page's brand treatment matches the product instead of inventing its own. */
function BrandMark({ size = 30, fontSize = 14 }: { size?: number; fontSize?: number }) {
  return (
    <div
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
        fontSize,
        fontFamily: "var(--font-family-display)",
        clipPath: "polygon(18% 0, 100% 0, 100% 82%, 82% 100%, 0 100%, 0 18%)",
      }}
    >
      P
    </div>
  );
}

/** Spec-plate header strip: monogram badge + label. `dark` is for use on a
 * dark header background (the six-modules cards) — badge flips to the
 * accent color and the label goes light; the default (light) treatment
 * matches the flagship recommendation card, which sits on a white surface. */
function SpecPlateHeader({ mono, label, dark = false }: { mono: string; label: React.ReactNode; dark?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      <span
        className="num"
        style={{
          width: 26,
          height: 26,
          borderRadius: 6,
          background: dark ? "var(--color-accent-600)" : "var(--color-chrome-950)",
          color: dark ? "var(--color-accent-ink)" : "#fff",
          fontSize: 10.5,
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
        }}
      >
        {mono}
      </span>
      <span style={{ fontSize: 13.5, fontWeight: 700, color: dark ? "#fff" : undefined }}>{label}</span>
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();

  /** The floating pill nav's "Home"/"Modules"/"Assistant" links are same-page
   * anchors, not routes — they scroll to the matching section below instead
   * of navigating away, since there's nothing past this page to link to for
   * an unauthenticated visitor. */
  const scrollToSection = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div>
      {/* ============ hero: dark industrial gradient + floating pill nav ============ */}
      <div
        id="home"
        style={{
          position: "relative",
          minHeight: 620,
          borderRadius: "0 0 28px 28px",
          overflow: "hidden",
          background:
            "radial-gradient(120% 100% at 78% 8%, rgba(255,255,255,.10), transparent 55%)," +
            "repeating-linear-gradient(115deg, rgba(255,255,255,.035) 0 2px, transparent 2px 46px)," +
            "linear-gradient(165deg, #3a3a3a, #161616 62%)",
        }}
      >
        {/* floating pill navbar */}
        <div
          style={{
            position: "absolute",
            top: 24,
            left: 24,
            right: 24,
            zIndex: 5,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            background: "rgba(16,16,16,.72)",
            backdropFilter: "blur(10px)",
            border: "1px solid rgba(255,255,255,.08)",
            borderRadius: 9999,
            padding: "8px 10px 8px 18px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 9, flex: "none" }}>
            <BrandMark size={26} fontSize={12} />
            <span style={{ fontFamily: "var(--font-family-display)", fontWeight: 800, fontSize: 15, color: "#fff", letterSpacing: "-.01em" }}>
              Plantwise
            </span>
          </div>
          <div style={{ display: "flex", gap: 6, fontSize: 13.5, fontWeight: 500 }}>
            {[
              { label: "Home", id: "home" },
              { label: "Modules", id: "modules" },
              { label: "Assistant", id: "assistant" },
            ].map((link) => (
              <button
                key={link.id}
                onClick={() => scrollToSection(link.id)}
                style={{
                  border: "none",
                  background: "transparent",
                  font: "inherit",
                  fontSize: 13.5,
                  fontWeight: 500,
                  color: link.id === "home" ? "#fff" : "#D9D9D6",
                  padding: "7px 12px",
                  borderRadius: 9999,
                  cursor: "pointer",
                }}
              >
                {link.label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
            <button
              onClick={() => navigate("/login")}
              style={{ border: "none", background: "transparent", color: "#fff", font: "inherit", fontSize: 13, fontWeight: 600, padding: "9px 14px", borderRadius: 9999, cursor: "pointer" }}
            >
              Log in
            </button>
            <button
              onClick={() => navigate("/signup")}
              style={{ border: "none", background: "rgba(255,255,255,.12)", color: "#fff", font: "inherit", fontSize: 12.5, fontWeight: 700, padding: "9px 16px", borderRadius: 9999, cursor: "pointer" }}
            >
              Sign up
            </button>
          </div>
        </div>

        {/* copy + "rig" graphic, both scaled against the same centered max-width
            as every other section below so the balance holds on wide viewports
            instead of the rig drifting off toward the edge with a dead gap
            opening up between it and the text column. */}
        <div style={{ position: "absolute", inset: 0, maxWidth: 1180, margin: "0 auto" }}>
          {/* real machinery photography (CNC head + robotic tooling arm),
              replacing the earlier abstract gradient placeholder — a soft
              dark gradient overlay blends its left edge into the hero's own
              background so it reads as one scene, not a pasted rectangle. */}
          <div
            style={{
              position: "absolute",
              right: 0,
              top: 0,
              bottom: 0,
              width: "50%",
              backgroundImage:
                "linear-gradient(100deg, #161616 0%, rgba(22,22,22,.55) 14%, rgba(22,22,22,0) 32%)," +
                "url(/images/hero-factory-square.png)",
              backgroundSize: "cover, cover",
              backgroundPosition: "center, center",
              backgroundRepeat: "no-repeat, no-repeat",
              clipPath: "polygon(10% 0, 100% 0, 100% 100%, 0 100%)",
            }}
          />

          {/* hero copy, bottom-left */}
          <div style={{ position: "relative", zIndex: 3, padding: "150px 32px 64px 32px", maxWidth: 580, color: "#fff" }}>
            <h1
              style={{
                fontSize: 50,
                lineHeight: 1.08,
                fontWeight: 800,
                letterSpacing: "-.025em",
                margin: "0 0 20px",
                textWrap: "balance",
              }}
            >
              Your Plant's Data,
              <br />
              Finally Assembled Into An Answer.
            </h1>
            <p style={{ fontSize: 16.5, lineHeight: 1.6, color: "rgba(255,255,255,.78)", margin: "0 0 26px", maxWidth: 520 }}>
              One dashboard and AI assistant for maintenance, production, inventory, quality and SOPs: set up with forms and
              spreadsheet uploads, no code required.
            </p>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <button
                onClick={() => navigate("/signup")}
                style={{
                  border: "none",
                  background: "var(--color-accent-600)",
                  color: "var(--color-accent-ink)",
                  font: "inherit",
                  fontSize: 15,
                  fontWeight: 800,
                  padding: "14px 24px",
                  borderRadius: 9999,
                  cursor: "pointer",
                }}
              >
                Start Free: Set Up in 30 Minutes
              </button>
              <button
                onClick={() => navigate("/login")}
                style={{
                  border: "1px solid rgba(255,255,255,.35)",
                  background: "transparent",
                  color: "#fff",
                  font: "inherit",
                  fontSize: 15,
                  fontWeight: 600,
                  padding: "14px 22px",
                  borderRadius: 9999,
                  cursor: "pointer",
                }}
              >
                See the Dashboard
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ============ intro strip + feature row (white, sits below the hero) ============ */}
      {/* A real gap (not a negative margin) so this panel's own top corners
          and drop shadow are actually visible against the page — nesting it
          flush against the hero's bottom edge left no room for either and
          read as the two containers colliding. */}
      <div
        style={{
          background: "#fff",
          border: "1px solid var(--color-border-default)",
          borderRadius: "28px 28px 0 0",
          margin: "28px 24px 0",
          position: "relative",
          zIndex: 4,
          padding: "56px 40px 0",
          boxShadow: "0 20px 50px -20px rgba(0,0,0,.28)",
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 40, marginBottom: 36, maxWidth: 1180, marginLeft: "auto", marginRight: "auto" }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: ".04em" }}>
            For discrete manufacturing
          </div>
          <div style={{ fontSize: 16.5, lineHeight: 1.55, color: "var(--color-text-primary)", fontWeight: 500 }}>
            Plantwise brings six operational modules and one AI assistant into a single view of the plant: maintenance,
            production, inventory, quality, SOPs and shift reports, configured with forms and spreadsheet uploads.
          </div>
        </div>

        <div style={{ maxWidth: 1180, margin: "0 auto", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, paddingBottom: 44 }}>
          {/* Each tile has two groups — the big number and the title+caption —
              stacked from the top with a fixed gap between them (not
              justifyContent: "space-between", which stretched that gap to
              swallow 100% of the card's leftover height and showed up as an
              oversized gap in the middle). The number still sits at the same
              height in every tile regardless of caption length, since it's
              always the first thing after the top padding. */}
          <div className="tab-card" style={{ "--tab-card-bg": "var(--color-accent-600)", "--tab-card-border": "transparent", color: "var(--color-accent-ink)", padding: "26px 22px", minHeight: 200, display: "flex", flexDirection: "column", gap: 22 } as React.CSSProperties}>
            <div style={{ fontFamily: "var(--font-family-display)", fontSize: 30, fontWeight: 800 }}>30 Min</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>To a populated dashboard</div>
              <div style={{ fontSize: 12.5, color: "#4a3a00", lineHeight: 1.4 }}>Forms, CSV templates, or load sample data.</div>
            </div>
          </div>

          <div
            className="tab-card"
            style={{
              position: "relative",
              minHeight: 200,
              padding: "26px 22px",
              display: "flex",
              flexDirection: "column",
              gap: 22,
              color: "#fff",
              "--tab-card-bg":
                "radial-gradient(60% 60% at 30% 20%, rgba(255,255,255,.12), transparent 65%)," +
                "linear-gradient(155deg, #3c3c3c, #131313 70%)",
              "--tab-card-border": "transparent",
            } as React.CSSProperties}
          >
            <span style={{ position: "absolute", top: 14, right: 18, display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: "#8FE3A6" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#3DDC73" }} />
              Live
            </span>
            <div style={{ fontFamily: "var(--font-family-display)", fontSize: 30, fontWeight: 800 }}>
              <span className="num">2.4</span> <span style={{ fontSize: 15, fontWeight: 600, opacity: 0.7 }}>mm/s</span>
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Compressor A-12: live reading</div>
              <div style={{ fontSize: 12.5, color: "rgba(255,255,255,.65)", lineHeight: 1.4 }}>Vibration, updated 20m ago, within normal range.</div>
            </div>
          </div>

          <div className="tab-card" style={{ "--tab-card-bg": "var(--color-accent-600)", "--tab-card-border": "transparent", color: "var(--color-accent-ink)", padding: "26px 22px", minHeight: 200, display: "flex", flexDirection: "column", gap: 22 } as React.CSSProperties}>
            <div style={{ fontFamily: "var(--font-family-display)", fontSize: 30, fontWeight: 800 }}>6</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Modules, one assistant</div>
              <div style={{ fontSize: 12.5, color: "#4a3a00", lineHeight: 1.4 }}>Maintenance, production, inventory, quality, SOP, shift reports.</div>
            </div>
          </div>
        </div>
      </div>

      {/* problem strip — dark control-panel chrome, matching the real sidebar */}
      <div style={{ background: "var(--color-chrome-950)", color: "#fff", padding: "48px 32px" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--color-primary-300)", marginBottom: 12 }}>
            The problem
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.01em", margin: "0 0 26px", maxWidth: 720 }}>
            Plants run on data that's scattered, stale, and locked in people's heads.
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
            {PROBLEMS.map((p) => (
              <div key={p.title} className="tab-card" style={{ "--tab-card-bg": "var(--color-chrome-800)", padding: 20 } as React.CSSProperties}>
                <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 8 }}>{p.title}</div>
                <div style={{ fontSize: 14, color: "var(--color-chrome-text)", lineHeight: 1.55 }}>{p.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* two pillars */}
      <div id="assistant" style={{ padding: "48px 32px", maxWidth: 1180, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--color-primary-700)", marginBottom: 10 }}>
            What you get on day one
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>Two things, on top of your data.</h2>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          <div
            className="tab-card"
            style={{ padding: 28, "--tab-card-bg": "var(--color-chrome-950)", "--tab-card-border": "transparent", color: "#fff", display: "flex", flexDirection: "column" } as React.CSSProperties}
          >
            <div style={{ width: 40, height: 40, borderRadius: 12, background: "var(--color-accent-600)", color: "var(--color-accent-ink)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, marginBottom: 16 }}>
              1
            </div>
            <h3 style={{ fontSize: 19, fontWeight: 800, margin: "0 0 8px", color: "#fff" }}>A unified operations dashboard</h3>
            <p style={{ fontSize: 14.5, color: "rgba(255,255,255,.7)", lineHeight: 1.55, margin: "0 0 14px" }}>
              One screen for maintenance, production, inventory, quality, SOPs and shift reports. Open alerts and
              recommendations show up first, so you always know what needs attention.
            </p>
            <button
              onClick={() => navigate("/login")}
              onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
              onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
              style={{ border: "none", background: "transparent", color: "var(--color-accent-600)", font: "inherit", fontSize: 14, fontWeight: 700, padding: 0, cursor: "pointer", textDecoration: "none", marginTop: "auto", alignSelf: "flex-start" }}
            >
              Preview the dashboard →
            </button>
          </div>
          <div
            className="tab-card"
            style={{ padding: 28, "--tab-card-bg": "var(--color-chrome-950)", "--tab-card-border": "transparent", color: "#fff", display: "flex", flexDirection: "column" } as React.CSSProperties}
          >
            <div style={{ width: 40, height: 40, borderRadius: 12, background: "var(--color-accent-600)", color: "var(--color-accent-ink)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, marginBottom: 16 }}>
              2
            </div>
            <h3 style={{ fontSize: 19, fontWeight: 800, margin: "0 0 8px", color: "#fff" }}>An AI assistant across every module</h3>
            <p style={{ fontSize: 14.5, color: "rgba(255,255,255,.7)", lineHeight: 1.55, margin: "0 0 14px" }}>
              Ask it whether a compressor is safe to run through the weekend, or why a line fell behind. It answers from
              your own data and documents, and always shows its sources.
            </p>
            <button
              onClick={() => navigate("/login")}
              onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
              onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
              style={{ border: "none", background: "transparent", color: "var(--color-accent-600)", font: "inherit", fontSize: 14, fontWeight: 700, padding: 0, cursor: "pointer", textDecoration: "none", marginTop: "auto", alignSelf: "flex-start" }}
            >
              Try the assistant →
            </button>
          </div>
        </div>
      </div>

      {/* flagship — dark control-panel chrome, same tone as the problem strip */}
      <div style={{ background: "linear-gradient(135deg, var(--color-chrome-950), var(--color-chrome-800))", color: "#fff", padding: "48px 32px" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto", display: "grid", gridTemplateColumns: ".95fr 1.05fr", gap: 48, alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--color-primary-300)", marginBottom: 12 }}>
              Flagship capability
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 14px" }}>
              Predictive maintenance you can actually explain.
            </h2>
            <p style={{ fontSize: 15, color: "rgba(255,255,255,.75)", lineHeight: 1.6, margin: "0 0 20px" }}>
              Plantwise watches sensor readings, maintenance history and service intervals, then flags early failure signatures
              with transparent rules, never a black box.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                "Threshold breaches, trend anomalies & overdue service intervals",
                "Structured recommendation with evidence and estimated window",
                "Auto-emailed at High urgency, acknowledge → action → shift report",
              ].map((text, i) => (
                <div key={text} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--color-fill-solid)", color: "var(--color-fill-solid-fg)", flex: "none", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800 }}>
                    {i + 1}
                  </span>
                  <span style={{ fontSize: 15, color: "rgba(255,255,255,.85)" }}>{text}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="pw-plate tab-card" style={{ "--tab-card-bg": "var(--color-surface-default)", "--tab-card-border": "transparent", padding: 22, color: "var(--color-text-primary)", boxShadow: "var(--shadow-lg)" } as React.CSSProperties}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <SpecPlateHeader
                mono="PM"
                label={
                  <span className="num" style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-tertiary)" }}>
                    REC-1042
                  </span>
                }
              />
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: "var(--color-success-700)" }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-success-500)" }} />
                <span className="num">20m ago</span>
              </span>
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 12 }}>
              Compressor <span className="num">A-12</span>: bearing wear
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 14 }}>
              <div style={{ background: "var(--color-neutral-50)", borderRadius: "var(--radius-lg)", padding: 12 }}>
                <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 3 }}>Urgency</div>
                <div style={{ fontWeight: 700, color: "var(--color-error-700)" }}>High</div>
              </div>
              <div style={{ background: "var(--color-neutral-50)", borderRadius: "var(--radius-lg)", padding: 12 }}>
                <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 3 }}>Window</div>
                <div style={{ fontWeight: 700 }}>Within 5 days</div>
              </div>
            </div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-tertiary)", marginBottom: 6 }}>
              Evidence
            </div>
            <div style={{ background: "var(--color-neutral-50)", borderRadius: "var(--radius-lg)", padding: 12, marginBottom: 14 }}>
              <div style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
                Vibration rose from <span className="num">2.1 → 2.8 mm/s</span> over 7 days (<span className="num">+34%</span>),
                approaching the <span className="num">3.0 mm/s</span> limit. Pattern matches the <span className="num">A-9</span>{" "}
                bearing failure logged 4 months ago.
              </div>
            </div>
            <button
              onClick={() => navigate("/login")}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-fill-solid-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "var(--color-fill-solid)"; }}
              style={{ width: "100%", border: "none", background: "var(--color-fill-solid)", color: "var(--color-fill-solid-fg)", font: "inherit", fontSize: 14, fontWeight: 700, padding: 12, borderRadius: "var(--radius-lg)", cursor: "pointer", transition: "background .15s ease" }}
            >
              Open full recommendation
            </button>
          </div>
        </div>
      </div>

      {/* six modules — spec-plate tiles, mono codes matching the real sidebar nav */}
      <div id="modules" style={{ padding: "48px 32px", maxWidth: 1180, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 8px" }}>Six modules, one shape.</h2>
          <p style={{ fontSize: 15, color: "var(--color-text-secondary)" }}>
            Configure once with a form, then keep it current with a daily upload.
          </p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
          {MODULES.map((m) => (
            <div
              key={m.mono}
              className="tab-card"
              style={{ "--tab-card-bg": "var(--color-surface-default)", overflow: "hidden" } as React.CSSProperties}
            >
              <div
                style={{
                  padding: "12px 16px",
                  background: "var(--color-chrome-950)",
                }}
              >
                <SpecPlateHeader mono={m.mono} label={m.title} dark />
              </div>
              <div style={{ padding: "16px 18px 18px" }}>
                <div style={{ fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{m.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* how it works */}
      <div style={{ background: "var(--color-neutral-50)", padding: "48px 32px", borderTop: "1px solid var(--color-border-default)" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 28px", textAlign: "center" }}>
            From sign-up to first prediction in under 30 minutes.
          </h2>
          {/* A real progress rail, not a card grid — the filled bar and the
              markers sitting on top of it read as "one continuous path,"
              which fits an onboarding flow better than separate boxes. */}
          <div style={{ position: "relative" }}>
            <div style={{ position: "absolute", top: 23, left: 48, right: 48, height: 4, borderRadius: 2, background: "var(--color-accent-600)" }} />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)" }}>
              {STEPS.map((st) => (
                <div key={st.n} style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", padding: "0 14px" }}>
                  <div
                    style={{
                      position: "relative",
                      width: 46,
                      height: 46,
                      borderRadius: "50%",
                      background: "var(--color-fill-solid)",
                      color: "var(--color-fill-solid-fg)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      marginBottom: 16,
                      border: "4px solid var(--color-neutral-50)",
                    }}
                  >
                    <st.Icon size={19} strokeWidth={1.8} />
                  </div>
                  <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>{st.title}</div>
                  <div style={{ fontSize: 13.5, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{st.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* trust */}
      <div style={{ padding: "48px 32px", maxWidth: 1180, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--color-primary-700)", marginBottom: 10 }}>
            Why plants trust it
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>Grounded in your data, not a black box.</h2>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20 }}>
          {TRUST.map((t) => (
            <div key={t.title} style={{ padding: 24, background: "var(--color-surface-default)", boxShadow: "var(--shadow-card)" }}>
              <div
                style={{
                  width: 46,
                  height: 46,
                  borderRadius: 12,
                  background: t.tint,
                  color: t.accent,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: 16,
                }}
              >
                <t.Icon size={21} strokeWidth={1.8} />
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15.5, marginBottom: 6 }}>{t.title}</div>
                <div style={{ fontSize: 13.5, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{t.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* final cta */}
      <div style={{ padding: "16px 32px 56px", maxWidth: 1180, margin: "0 auto" }}>
        <div className="tab-card" style={{ "--tab-card-bg": "var(--color-chrome-950)", "--tab-card-border": "transparent", padding: 40, textAlign: "center", color: "#fff" } as React.CSSProperties}>
          <h2 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 10px" }}>Bring your plant's data into focus.</h2>
          <p style={{ fontSize: 15.5, color: "rgba(255,255,255,.75)", margin: "0 0 22px" }}>
            Sign up, load your assets and a CSV/Excel file, and watch the first recommendations appear.
          </p>
          <button
            onClick={() => navigate("/signup")}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-accent-700)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "var(--color-accent-600)"; }}
            style={{ border: "none", background: "var(--color-accent-600)", color: "var(--color-accent-ink)", font: "inherit", fontSize: 15, fontWeight: 800, padding: "13px 26px", borderRadius: 9999, cursor: "pointer", transition: "background .15s ease" }}
          >
            Start Free
          </button>
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--color-border-default)", padding: "28px 32px", maxWidth: 1180, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", color: "var(--color-text-tertiary)", fontSize: 13, flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <BrandMark size={22} fontSize={11} />
          <span>
            <strong style={{ color: "var(--color-text-secondary)", fontWeight: 700 }}>Plantwise</strong>: Manufacturing Operations Assistant
          </span>
        </div>
        <span>v1 · Discrete manufacturing · SMTP alerts · AI-powered assistant</span>
      </div>
    </div>
  );
}

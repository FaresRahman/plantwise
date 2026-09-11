import React, { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

/**
 * The "manual entry / upload" card recipe from Admin's Users tab ("Invite a
 * Teammate"), extracted so every module page's add-form/import section uses
 * the same container instead of a one-off `<h3>` + plain padding: a surface
 * card, a display-font title, a secondary-color subtitle, and an optional
 * right-aligned header action — never the admin page itself, which stays as
 * the reference and isn't touched by this component.
 */
export function FormSection({
  title,
  subtitle,
  actions,
  children,
  collapsible,
  defaultOpen = true,
}: {
  title: string;
  subtitle?: React.ReactNode;
  /** Right-aligned header control, e.g. Admin's "Invite Several at Once" toggle. */
  actions?: React.ReactNode;
  children: React.ReactNode;
  /** When set, the header becomes a toggle (chevron top-right) that shows/hides children. */
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = !collapsible || open;

  return (
    <div className="surface" style={{ padding: 20, marginBottom: 16 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: isOpen ? 16 : 0,
          cursor: collapsible ? "pointer" : undefined,
        }}
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      >
        <div>
          <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700 }}>{title}</div>
          {subtitle && (
            <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 3, lineHeight: 1.6 }}>{subtitle}</div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flex: "none" }}>
          {actions}
          {collapsible && (
            <button
              type="button"
              className="btn-chevron"
              onClick={(e) => {
                e.stopPropagation();
                setOpen((o) => !o);
              }}
              aria-label={isOpen ? "Collapse" : "Expand"}
              aria-expanded={isOpen}
            >
              {isOpen ? <ChevronUp size={18} strokeWidth={2} /> : <ChevronDown size={18} strokeWidth={2} />}
            </button>
          )}
        </div>
      </div>
      {isOpen && children}
    </div>
  );
}

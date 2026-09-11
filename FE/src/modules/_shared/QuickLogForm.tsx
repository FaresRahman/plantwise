import React, { useState } from "react";

/** Same tinted inset-zone treatment the onboarding "Add asset" quick-add
 * form uses (see modules/onboarding/steps.tsx's quickAddCardStyle) — every
 * quick-log form should read as the same kind of zone, not a mix of gray
 * insets and white surface cards. */
const quickLogCardStyle: React.CSSProperties = {
  background: "var(--color-neutral-100)",
  borderRadius: "var(--radius-lg)",
  padding: 16,
  marginBottom: 6,
};

interface QuickLogFormProps {
  submitLabel?: string;
  onSubmit: () => Promise<void>;
  /** Reset any local field state after a successful submit (kept separate
   * from onSubmit so callers don't have to remember to do it themselves). */
  onSubmitted?: () => void;
  children: React.ReactNode;
  disabled?: boolean;
  /** db_import entity key this form also feeds — the "syncing automatically"
   * banner this used to show here now lives one level up, in
   * ConfigImportTabs (covers File Upload too, not just Manual Entry). Kept
   * as a prop for caller back-compat even though unused here now. */
  syncEntity?: string;
  /** Skip the transient "Logged ✓" message — for callers (sensor readings,
   * maintenance history) that show a persistent list of what's been logged
   * instead, which is a clearer confirmation than a message that vanishes. */
  hideSuccessMessage?: boolean;
}

/**
 * Single-row "quick log" card — the lightweight alternative to building a CSV
 * for one row (PRD §4.9's "quick daily form" for small daily updates, e.g.
 * "today's output number, current stock"). Every operational-data module
 * pairs one of these with its <CsvUploadFlow> rather than forcing a CSV even
 * for a single ad-hoc entry. No title/description of its own — the section
 * it's embedded in already has one (e.g. "Sensor readings"); repeating it
 * here read as a second, redundant heading.
 */
export function QuickLogForm({ submitLabel = "Log entry", onSubmit, onSubmitted, children, disabled, hideSuccessMessage }: QuickLogFormProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await onSubmit();
      setSuccess(true);
      onSubmitted?.();
      window.setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={quickLogCardStyle}>
      <form
        onSubmit={handleSubmit}
        noValidate
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, alignItems: "end" }}
      >
        {children}
        <div style={{ gridColumn: "1 / -1", display: "flex", gap: 10, alignItems: "center", justifyContent: "flex-end" }}>
          <button className="btn-primary" type="submit" disabled={saving || disabled}>
            {saving ? "Logging…" : submitLabel}
          </button>
          {!hideSuccessMessage && success && <span style={{ color: "var(--color-success-700)", fontSize: 12.5, fontWeight: 700 }}>Logged ✓</span>}
        </div>
      </form>
      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 10 }}>{error}</div>}
    </div>
  );
}

export const quickFieldStyle: React.CSSProperties = { display: "flex", flexDirection: "column", fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", gap: 4 };

/**
 * Field hint lives inside the control (placeholder text / a disabled first
 * option), matching the onboarding "Add asset" form's convention — not as a
 * separate label sitting above it. Still fully accessible: the label text
 * becomes the control's aria-label (and its placeholder, unless the control
 * already set a more specific example value like "mm/s").
 */
export function QuickField({
  label,
  style,
  width,
  children,
}: {
  label: string;
  /** Layout sizing (flex-basis, grid-column, ...) that used to live on the
   * <label> wrapper — merged onto the control itself now that there's no
   * wrapper element. */
  style?: React.CSSProperties;
  /** Fixed width (px) for a field that needs more or less room than the
   * surrounding grid/flex gives it by default — e.g. a longer free-text
   * field beside several short ones. Shorthand for `style={{ width }}`. */
  width?: number;
  children: React.ReactElement<{ placeholder?: string; "aria-label"?: string; style?: React.CSSProperties }>;
}) {
  const mergedStyle = width !== undefined || style ? { ...children.props.style, ...(width !== undefined ? { width } : null), ...style } : children.props.style;
  return React.cloneElement(children, {
    placeholder: children.props.placeholder ?? label,
    "aria-label": label,
    style: mergedStyle,
  });
}

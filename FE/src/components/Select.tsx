import React from "react";
import { ChevronDown } from "lucide-react";

/** Native <select> elements render the browser's own dropdown arrow, which
 * doesn't line up with the rest of the site's form-control styling (wrong
 * inset, system font) — and unlike a text input, padding-right alone can't
 * push a native select's arrow away from the edge, since the browser draws
 * it in its own reserved area regardless of the element's padding. Keep the
 * real <select> for behavior/accessibility but hide its native arrow and
 * draw our own, consistently positioned, icon on top instead. */
export function Select({
  value,
  onChange,
  options,
  placeholder,
  compact,
  pill,
  disabled,
  style,
  "aria-label": ariaLabel,
}: {
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  options: readonly { value: string | number; label: string }[];
  /** Shown as a disabled first option when nothing is selected yet — for a
   * real hint instead of silently defaulting to the first real choice. */
  placeholder?: string;
  compact?: boolean;
  /** Fully-rounded chip shape, for the small period/criticality filters on
   * dashboard charts (matches the reference design's rounded filter pills)
   * instead of the standard form-field corner radius. */
  pill?: boolean;
  /** For a field that depends on another choice made first (e.g. Metric
   * before an Asset is picked) — blocks interaction and reads as muted via
   * .input:disabled instead of silently having nothing to pick from. */
  disabled?: boolean;
  style?: React.CSSProperties;
  /** For fields whose hint lives in `placeholder` instead of a visible
   * label — keeps the control accessible without a <label> element. */
  "aria-label"?: string;
}) {
  // Matches .input::placeholder's tertiary gray on text fields — a native
  // <select> has no placeholder concept of its own, so without this the
  // disabled placeholder option reads as a normal, already-chosen value
  // instead of an unset hint.
  const showingPlaceholder = !!placeholder && (value === "" || value == null);
  // Set unconditionally (not just when showing the hint) and mirrored onto
  // WebkitTextFillColor: WebKit/Blink paint a disabled control's text via
  // -webkit-text-fill-color rather than color, ignoring plain `color`
  // entirely — .input:disabled's CSS-level color would otherwise win over
  // this and flatten the hint back to normal text color while disabled.
  const textColor = showingPlaceholder ? "var(--color-text-tertiary)" : "var(--color-text-primary)";
  return (
    <div className="pw-select" style={style}>
      <select
        className="input pw-select__native"
        style={{
          ...(compact ? { height: 32, fontSize: 13 } : undefined),
          ...(pill ? { borderRadius: 9999, fontWeight: 700 } : undefined),
          color: textColor,
          WebkitTextFillColor: textColor,
        }}
        value={value}
        onChange={onChange}
        disabled={disabled}
        aria-label={ariaLabel}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((o) => (
          // Explicit color, not inherited — otherwise the gray set on the
          // <select> for the placeholder state bleeds into every real choice
          // in the dropdown list too, not just the closed box.
          <option key={o.value} value={o.value} style={{ color: "var(--color-text-primary)" }}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={14} strokeWidth={2} className="pw-select__chevron" aria-hidden="true" />
    </div>
  );
}

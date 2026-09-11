import React from "react";

/** Renders a CSV/DB column list as inline code chips instead of a raw
 * comma-separated string of snake_case names — reads as a quick-reference
 * schema hint, not run-on prose. Pair with an optional plain-English
 * `intro` sentence for context (e.g. what one row represents). */
export function FieldChips({ intro, fields }: { intro?: React.ReactNode; fields: string[] }) {
  return (
    <>
      {intro}
      {intro ? " " : null}
      {fields.map((f) => (
        <code key={f} className="field-chip">
          {f}
        </code>
      ))}
    </>
  );
}

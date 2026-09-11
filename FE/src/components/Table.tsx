import React from "react";

/**
 * Real semantic <table> primitives styled as a "spec sheet" — hairline
 * rows, mono tabular-numeral columns. Replaces the div-grid pseudo-tables
 * (gridTemplateColumns hardcoded per page) that every module used to
 * hand-roll independently.
 *
 *   <Table>
 *     <THead><tr><Th>Asset</Th><Th numeric>Value</Th></tr></THead>
 *     <TBody>
 *       <Tr onClick={...}><Td>CNC-04</Td><Td numeric>4.8</Td></Tr>
 *     </TBody>
 *   </Table>
 */
export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="sheet">
      <div className="sheet-scroll">
        <table>{children}</table>
      </div>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return <thead>{children}</thead>;
}

export function TBody({ children }: { children: React.ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function Tr({
  children,
  onClick,
  active,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  /** Marks this row as the current selection (e.g. it drives a headline
   * card elsewhere on the page) — rendered with a background tint + left
   * accent bar so the selection reads clearly, not just a subtle dot. */
  active?: boolean;
}) {
  return (
    <tr data-clickable={onClick ? "true" : undefined} data-active={active ? "true" : undefined} onClick={onClick}>
      {children}
    </tr>
  );
}

export function Th({ children, numeric, align }: { children: React.ReactNode; numeric?: boolean; align?: "right" | "center" }) {
  return <th className={numeric ? "num" : undefined} style={align ? { textAlign: align } : undefined}>{children}</th>;
}

/** `align="right"` lines a header up with content that's right-aligned for
 * layout reasons (e.g. RowActions' icon buttons) without pulling in `.num`'s
 * monospace/tabular-figure styling, which is only correct for actual numbers.
 * `align="center"` overrides `numeric`'s own default right-align, for a
 * numeric column that reads better centered than flush right. */
export function Td({
  children,
  numeric,
  wrap,
  align,
  top,
}: {
  children: React.ReactNode;
  numeric?: boolean;
  wrap?: boolean;
  align?: "right" | "center";
  /** Anchors this cell to the row's top instead of the default vertical
   * center — for a row with a `wrap` sibling cell that can grow to several
   * lines, so a single-line cell (e.g. a number) sits directly under its
   * header instead of drifting to the middle of a now-taller row. */
  top?: boolean;
}) {
  return (
    <td
      className={numeric ? "num" : undefined}
      style={{
        ...(wrap ? { whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.4 } : { whiteSpace: "nowrap" }),
        ...(align ? { textAlign: align } : null),
        ...(top ? { verticalAlign: "top" } : null),
      }}
    >
      {children}
    </td>
  );
}

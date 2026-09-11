import React from "react";
import { BadgeCheck, BookOpen, Boxes, ClipboardList, Database, Factory, ShieldCheck, Users, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** Consistent page header used across every module page: icon + title +
 * subtitle on the left, primary action(s) on the right. One component so
 * every page reads as the same product instead of each one improvising its
 * own header layout. */
export function PageHeader({
  icon,
  title,
  subtitle,
  actions,
}: {
  icon?: React.ReactNode;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22, gap: 16, flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {icon && (
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: 12,
              background: "var(--color-primary-50)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
              color: "var(--color-primary-600)",
            }}
          >
            {icon}
          </div>
        )}
        <div>
          <h1 style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-.015em", lineHeight: 1.15 }}>{title}</h1>
          {subtitle && <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", marginTop: 4, lineHeight: 1.3 }}>{subtitle}</div>}
        </div>
      </div>
      {actions && <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
    </div>
  );
}

const ICON_MAP: Record<string, LucideIcon> = {
  maintenance: Wrench,
  production: Factory,
  inventory: Boxes,
  quality: BadgeCheck,
  sop: BookOpen,
  shift: ClipboardList,
  admin: ShieldCheck,
  invite: Users,
  database: Database,
};

/** Small icon set matching each module, used as PageHeader's `icon` prop so
 * every page's header icon is drawn the same way (size, stroke width). */
export function ModuleIcon({ name }: { name: keyof typeof ICON_MAP }) {
  const Icon = ICON_MAP[name] ?? Wrench;
  return <Icon size={21} strokeWidth={1.8} />;
}

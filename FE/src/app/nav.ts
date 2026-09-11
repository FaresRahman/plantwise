export type Role = "admin" | "operator" | "viewer";

export interface NavItem {
  label: string;
  path: string;
  /** 2-letter monogram badge, matching the wireframe sidebar's mono squares. */
  mono: string;
  group: "Operate" | "Modules" | "Admin";
  roles: Role[];
}

/**
 * Sidebar nav — APPEND-ONLY. Add your module's entry at the end of this
 * array; don't reorder or restructure the file. See DEV_BRIEF section 4.6.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", path: "/", mono: "DB", group: "Operate", roles: ["admin", "operator", "viewer"] },
  { label: "Plantwise AI", path: "/chat", mono: "AI", group: "Operate", roles: ["admin", "operator", "viewer"] },

  // --- Dev A ---
  { label: "Predictive Maintenance", path: "/predictive-maintenance", mono: "PM", group: "Modules", roles: ["admin", "operator", "viewer"] },
  { label: "Production", path: "/production", mono: "PR", group: "Modules", roles: ["admin", "operator", "viewer"] },
  { label: "Inventory", path: "/inventory", mono: "IN", group: "Modules", roles: ["admin", "operator", "viewer"] },
  { label: "Quality", path: "/quality", mono: "QA", group: "Modules", roles: ["admin", "operator", "viewer"] },

  // --- Dev B ---
  { label: "SOP Library", path: "/sop", mono: "SO", group: "Modules", roles: ["admin", "operator", "viewer"] },
  { label: "Shift Reports", path: "/shift-reports", mono: "SR", group: "Modules", roles: ["admin", "operator", "viewer"] },
  { label: "Admin", path: "/admin", mono: "AD", group: "Admin", roles: ["admin"] },
];

export const NAV_GROUP_ORDER: NavItem["group"][] = ["Operate", "Modules", "Admin"];

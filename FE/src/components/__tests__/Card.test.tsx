import { describe, it, expect } from "vitest";
import { render, screen } from "../../test/test-utils";
import { Card } from "../Card";
import { ModuleSummary } from "../../api/dashboard";

const mockSummary: ModuleSummary = {
  module: "predictive_maintenance",
  title: "Predictive Maintenance",
  headline: "2 open recommendations",
  status: "warning",
  metrics: [{ label: "Health Score", value: "87" }],
  alerts_count: 2,
  last_updated_at: new Date().toISOString(),
  is_stale: false,
  expected_cadence_hours: 24,
  drilldown_path: "/predictive-maintenance",
};

describe("Card", () => {
  it("renders the module title", () => {
    render(<Card summary={mockSummary} />);
    expect(screen.getByText("Predictive Maintenance")).toBeInTheDocument();
  });

  it("renders the headline", () => {
    render(<Card summary={mockSummary} />);
    expect(screen.getByText("2 open recommendations")).toBeInTheDocument();
  });

  it("renders the primary metric value", () => {
    render(<Card summary={mockSummary} />);
    expect(screen.getByText("87")).toBeInTheDocument();
  });

  it("makes the whole card the click target when not readonly", () => {
    const { container } = render(<Card summary={mockSummary} />);
    expect(container.firstElementChild).toHaveStyle({ cursor: "pointer" });
  });

  it("stays clickable when readonly — read-only blocks actions on the destination page, not navigation to it", () => {
    const { container } = render(<Card summary={mockSummary} readonly />);
    expect(container.firstElementChild).toHaveStyle({ cursor: "pointer" });
  });
});

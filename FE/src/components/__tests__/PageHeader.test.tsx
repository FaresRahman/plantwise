import { describe, it, expect } from "vitest";
import { render, screen } from "../../test/test-utils";
import { PageHeader, ModuleIcon } from "../../components/PageHeader";

describe("PageHeader", () => {
  it("renders title and subtitle", () => {
    render(
      <PageHeader
        title="Predictive Maintenance"
        subtitle="Asset health overview"
        icon={<ModuleIcon name="maintenance" />}
      />
    );
    expect(screen.getByText("Predictive Maintenance")).toBeDefined();
    expect(screen.getByText("Asset health overview")).toBeDefined();
  });

  it("renders without icon", () => {
    render(<PageHeader title="Admin Console" />);
    expect(screen.getByText("Admin Console")).toBeDefined();
  });

  it("renders with actions", () => {
    render(
      <PageHeader
        title="Settings"
        actions={<button>Import CSV</button>}
      />
    );
    expect(screen.getByText("Settings")).toBeDefined();
    expect(screen.getByText("Import CSV")).toBeDefined();
  });
});

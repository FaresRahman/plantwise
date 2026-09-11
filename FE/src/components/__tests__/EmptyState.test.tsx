import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "../../components/EmptyState";
import { AllTheProviders } from "../../test/test-utils";

describe("EmptyState", () => {
  it("renders title and message", () => {
    render(
      <EmptyState title="No items" message="Nothing to show yet." />,
      { wrapper: AllTheProviders }
    );
    expect(screen.getByText("No items")).toBeDefined();
    expect(screen.getByText("Nothing to show yet.")).toBeDefined();
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "../../test/test-utils";
import { ErrorBoundary } from "../../components/ErrorBoundary";

function ExplodingComponent(): JSX.Element {
  throw new Error("Boom!");
}

describe("ErrorBoundary", () => {
  it("renders fallback when child throws", () => {
    // Suppress console.error for the expected throw
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <ExplodingComponent />
      </ErrorBoundary>
    );
    expect(screen.getByText(/something went wrong/i)).toBeDefined();
    spy.mockRestore();
  });
});

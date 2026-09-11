/** Tests for the FreshnessBadge component.
 *
 * The badge renders 3 states:
 * - green "updated Xh ago" when fresh (is_stale=false)
 * - amber "stale" when past expected cadence but within 3x
 * - red "overdue" when way past cadence
 * - gray "No data yet" when last_updated_at is null
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FreshnessBadge } from "../../components/FreshnessBadge";
import { AllTheProviders } from "../../test/test-utils";

describe("FreshnessBadge", () => {
  it("shows fresh indicator when not stale", () => {
    render(
      <FreshnessBadge
        lastUpdatedAt={new Date().toISOString()}
        isStale={false}
        expectedCadenceHours={24}
      />,
      { wrapper: AllTheProviders }
    );
    expect(screen.getByText(/updated/i)).toBeDefined();
  });

  it("shows stale indicator when stale", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    render(
      <FreshnessBadge
        lastUpdatedAt={twoDaysAgo}
        isStale={true}
        expectedCadenceHours={24}
      />,
      { wrapper: AllTheProviders }
    );
    expect(screen.getByText(/stale/i)).toBeDefined();
  });

  it("shows no-data indicator when no timestamp", () => {
    render(
      <FreshnessBadge
        lastUpdatedAt={null}
        isStale={false}
        expectedCadenceHours={24}
      />,
      { wrapper: AllTheProviders }
    );
    expect(screen.getByText(/no data/i)).toBeDefined();
  });
});

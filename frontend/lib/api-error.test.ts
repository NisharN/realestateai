import { describe, expect, it } from "vitest";

import { normalizeApiError } from "./api";

describe("normalizeApiError", () => {
  it("returns string details unchanged", () => {
    expect(normalizeApiError({ detail: "Not authorized" })).toBe("Not authorized");
  });

  it("extracts the message from structured provider errors", () => {
    expect(
      normalizeApiError({
        detail: { code: "service_unavailable", message: "Database request failed" },
      }),
    ).toBe("Database request failed");
  });

  it("never returns a render-unsafe object", () => {
    expect(normalizeApiError({ detail: { code: "unknown" } })).toBe("An error occurred");
  });
});

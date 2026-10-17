import { describe, expect, it } from "vitest";
import { presetRange, query } from "./Reports";

describe("report period presets", () => {
  // Periods end on the data's last date (imported data can lag behind today).
  const last = "2026-10-13";

  it.each([
    ["this-month", "2026-10-01", "2026-10-13"],
    ["3m", "2026-08-01", "2026-10-13"],
    ["6m", "2026-05-01", "2026-10-13"],
    ["12m", "2025-11-01", "2026-10-13"],
    ["ytd", "2026-01-01", "2026-10-13"],
    ["last-year", "2025-01-01", "2025-12-31"],
  ] as const)("%s runs from %s to %s", (preset, start, end) => {
    expect(presetRange(preset, last)).toEqual([start, end]);
  });

  it("crosses year boundaries correctly", () => {
    expect(presetRange("3m", "2026-01-20")).toEqual(["2025-11-01", "2026-01-20"]);
  });
});

describe("report query strings", () => {
  it("skips empty filters and encodes values", () => {
    expect(query({ start: "2026-01-01", category: "", accountId: null, q: "flour & co" }))
      .toBe("?start=2026-01-01&q=flour+%26+co");
    expect(query({})).toBe("");
  });
});

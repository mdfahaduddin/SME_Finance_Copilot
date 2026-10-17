import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { downloadFile } from "./download";

describe("downloadFile", () => {
  let clicked: HTMLAnchorElement[];

  beforeEach(() => {
    clicked = [];
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uses the file name the server chose (business and period)", async () => {
    const fetchMock = vi.fn(async () => new Response("a,b\n1,2\n", {
      headers: { "content-disposition": 'attachment; filename="lotus-profit-and-loss-2025-11-01-2026-10-13.csv"' },
    }));
    vi.stubGlobal("fetch", fetchMock);
    await downloadFile("/reports/pnl?format=csv", "fallback.csv");
    expect(fetchMock).toHaveBeenCalledWith("/api/reports/pnl?format=csv", { credentials: "same-origin" });
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("lotus-profit-and-loss-2025-11-01-2026-10-13.csv");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });

  it("falls back to the given name", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x")));
    await downloadFile("/audit/export", "audit-log.csv");
    expect(clicked[0].download).toBe("audit-log.csv");
  });

  it("surfaces the server's error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Choose a period of at most 3 years" }),
      { status: 422, statusText: "Unprocessable Entity", headers: { "content-type": "application/json" } })));
    const error = await downloadFile("/reports/pnl?format=xlsx", "x.xlsx").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toBe("Choose a period of at most 3 years");
    expect(clicked).toHaveLength(0);
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { money as format, pct, setDefaultCurrency } from "./format";

// Intl puts a non-breaking space after currency codes ("BDT\u00a0610,000"); compare with plain spaces.
const money = (...args: Parameters<typeof format>) => format(...args).replace(/\u00a0/g, " ");

describe("money", () => {
  afterEach(() => setDefaultCurrency(undefined));

  it("formats in the business currency set at sign-in", () => {
    expect(money(1234.5)).toBe("$1,235");
    setDefaultCurrency("BDT");
    expect(money(610000)).toBe("BDT 610,000");
    expect(money(-5000)).toBe("-BDT 5,000");
  });

  it("can be given a currency and a compact form", () => {
    expect(money(1_200_094, "USD", true)).toBe("$1.2M");
    expect(money(45000, "EUR")).toBe("€45,000");
  });

  it("falls back to USD when no currency is known", () => {
    setDefaultCurrency("");
    expect(money(10)).toBe("$10");
  });
});

describe("pct", () => {
  it("turns ratios into percentages", () => {
    expect(pct(0.0389)).toBe("3.9%");
    expect(pct(0.5, 0)).toBe("50%");
  });
});
